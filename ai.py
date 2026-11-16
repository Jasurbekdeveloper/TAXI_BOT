"""AI (OpenAI-mos API: Groq, OpenRouter, Gemini va h.k.).

classify()   — xabar egasi kim: yo'lovchi (passenger), haydovchi (driver) yoki boshqa (other) + ishonch darajasi.
               Kalit so'zlar noaniq bo'lsa YOKI "yo'lovchi" natijasida haydovchi belgilari ham bo'lsa chaqiriladi
               (pipeline.process). Bir xil matn (bir e'lon ko'p guruhga tashlanadi) keshdan olinadi.
extract_ad() — haydovchi e'lonidan maydonlarni ajratadi (services/ad_format.py uchun).
AI javobiga ishonilmaydi: clean_* funksiyalari faqat kutilgan tur va qiymatlarni o'tkazadi.
"""
import asyncio
import json
import logging
import re
import time
from collections import OrderedDict

import httpx

import config
from nlp import normalize

log = logging.getLogger(__name__)
_limit = asyncio.Semaphore(3)       # katta guruhlarda bepul API limitiga urilmaslik uchun
CACHE_TTL = 3600
CACHE_MAX = 2000
_cache: OrderedDict = OrderedDict()  # normallashtirilgan matn -> (vaqt, natija)

PROMPT = """Sen O'zbekistondagi taksi Telegram guruhlaridagi xabarlarni tahlil qilasan. Xabar o'zbek (lotin yoki kirill), rus yoki aralash tilda, imlo xatolari, emoji va KATTA harflar bilan bo'lishi mumkin.

Vazifa: xabar EGASI kimligini aniqla.
- "passenger" — yo'lovchi yoki pochta jo'natuvchi: mashina/taksi QIDIRYAPTI. Belgilar: "taksi kerak", "mashina bormi", "ketishim kerak", "2 kishimiz", "joy bormi", "pochta jo'nataman", "kim olib ketadi", "нужно такси", "ищу машину".
- "driver" — haydovchi: o'zi yo'lga chiqyapti va yo'lovchi yoki pochta QIDIRYAPTI. Belgilar: "ketamiz/ketyapman" bilan birga "joy bor", "3 ta joy", "bo'sh joy", "oldi bo'sh", "2 kishi kerak", "odam olaman", "yo'lovchi kerak", "pochta olamiz", "ayol kishi bor" (mashinada allaqachon ayol yo'lovchi bor), mashina nomi (Cobalt, Gentra, Nexia, Malibu...), "kim bor?", "беру пассажиров", "есть места".
- "other" — reklama, savol, salomlashish, guruh qoidasi va boshqalar.

Muhim: "ketaman/ketamiz" ni ham yo'lovchi, ham haydovchi yozadi — kim KIMNI qidirayotganiga qara. Haydovchi e'lonida ko'pincha oraliq shaharlar ro'yxati, bir nechta telefon va "joy bor" bo'ladi. Ikkilansang confidence ni past qo'y.

Faqat JSON qaytar, boshqa matnsiz:
{"label": "passenger|driver|other", "confidence": 0.0-1.0, "from": "shahar"|null, "to": "shahar"|null, "seats": son|null, "time": "matn"|null}
Shahar nomlarini o'zbek lotin yozuvida yoz: Toshkent, Samarqand, Termiz, Surxondaryo, Buxoro..."""

FEW_SHOT = [
    ("Termizdan Toshkentga taksi kerak 2 kishi ertaga +998901234567",
     {"label": "passenger", "confidence": 0.97, "from": "Termiz", "to": "Toshkent", "seats": 2, "time": "ertaga"}),
    ("СУРХОНДАРЁДАН ТОШКЕНТ КЕТАМИЗ 2⃣киши керак ТЕРМИЗ АНГОР ШЕРАБОТДАН 👠 айол киши бор 📦 Почта хам оламиз Тел +998991930666",
     {"label": "driver", "confidence": 0.96, "from": "Surxondaryo", "to": "Toshkent", "seats": 2, "time": None}),
    ("Toshkentga ketaman, kim olib ketadi? 1 kishi",
     {"label": "passenger", "confidence": 0.85, "from": None, "to": "Toshkent", "seats": 1, "time": None}),
    ("Hozir Samarqandga chiqamiz, Gentra, 3 joy bo'sh",
     {"label": "driver", "confidence": 0.95, "from": None, "to": "Samarqand", "seats": 3, "time": "hozir"}),
    ("Assalomu alaykum guruhga xush kelibsiz, reklama taqiqlanadi",
     {"label": "other", "confidence": 0.95, "from": None, "to": None, "seats": None, "time": None}),
]

AD_PROMPT = """Sen taksi haydovchisining e'lon matnidan ma'lumot ajratasan. Matn o'zbek (lotin/kirill) yoki rus tilida.
Faqat JSON qaytar:
{"from": "shahar"|null, "to": "shahar"|null, "stops": ["oraliq shahar/tuman", ...], "time": "matn"|null,
 "seats": bo'sh joy soni|null, "car": "mashina"|null, "price": "narx matni"|null, "phones": ["+998..."],
 "pochta": true|false, "ayol": true|false, "oldi_bosh": true|false, "konditsioner": true|false, "bagaj": true|false}
Shahar va tuman nomlarini o'zbek lotin yozuvida, bosh harf bilan yoz. Matnda yo'q narsani to'qima — null yoki false qo'y."""


# ---------- tozalash ----------
def _text(v, n=60) -> str | None:
    return (v.strip()[:n] or None) if isinstance(v, str) else None


def _seats(v) -> int | None:
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8 else None


def _conf(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.7                       # model ishonchni bermasa: o'rtacha
    return min(max(float(v), 0.0), 1.0)


def clean(data) -> dict | None:
    """AI javobiga ishonib bo'lmaydi: faqat kutilgan tur va qiymatlar o'tadi."""
    if not isinstance(data, dict):
        return None
    label = data.get("label")
    return {
        "label": label if label in ("passenger", "driver", "other") else "unknown",
        "confidence": _conf(data.get("confidence")),
        "from": _text(data.get("from")), "to": _text(data.get("to")),
        "seats": _seats(data.get("seats")), "time": _text(data.get("time")),
    }


def clean_ad(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    lst = lambda v: [x.strip()[:40] for x in v if isinstance(x, str) and x.strip()][:8] if isinstance(v, list) else []  # noqa: E731
    return {
        "from": _text(data.get("from")), "to": _text(data.get("to")), "stops": lst(data.get("stops")),
        "time": _text(data.get("time")), "seats": _seats(data.get("seats")), "car": _text(data.get("car"), 30),
        "price": _text(data.get("price"), 40), "phones": lst(data.get("phones")),
        **{k: data.get(k) is True for k in ("pochta", "ayol", "oldi_bosh", "konditsioner", "bagaj")},
    }


def parse_json(content: str):
    """Model JSON atrofiga matn yoki ```json``` qo'shsa ham o'qiydi."""
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        pass
    m = re.search(r"\{.*\}", content or "", re.S)
    if m:
        try:
            return json.loads(m.group())
        except ValueError:
            return None
    return None


# ---------- so'rov ----------
async def _chat(messages: list[dict]) -> str | None:
    async with _limit, httpx.AsyncClient(timeout=20) as c:
        for attempt in (1, 2):
            r = await c.post(
                f"{config.AI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.AI_API_KEY}"},
                json={"model": config.AI_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                      "messages": messages},
            )
            if r.status_code == 429 and attempt == 1:       # bepul limit: bir marta kutib qayta
                await asyncio.sleep(min(float(r.headers.get("retry-after", 2) or 2), 10))
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    return None


def _cache_get(key):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key, value):
    _cache[key] = (time.time(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)


async def classify(text: str) -> dict | None:
    if not config.AI_API_KEY:
        return None
    key = normalize(text)[:400]
    cached = _cache_get(key)
    if cached is not None:
        return cached
    msgs = [{"role": "system", "content": PROMPT}]
    for q, a in FEW_SHOT:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a, ensure_ascii=False)}]
    msgs.append({"role": "user", "content": text[:800]})
    try:
        res = clean(parse_json(await _chat(msgs)))
    except Exception as e:  # AI ishlamasa bot to'xtamasin
        log.warning("AI xatosi: %s", e)
        return None
    if res:
        _cache_put(key, res)
    return res


async def extract_ad(text: str) -> dict | None:
    if not config.AI_API_KEY:
        return None
    try:
        return clean_ad(parse_json(await _chat([{"role": "system", "content": AD_PROMPT},
                                                {"role": "user", "content": text[:1000]}])))
    except Exception as e:
        log.warning("AI (e'lon) xatosi: %s", e)
        return None
