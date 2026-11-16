"""Faqat noaniq xabarlar uchun bepul AI (OpenAI-mos API: Groq, OpenRouter, Gemini va h.k.)."""
import asyncio
import json
import logging

import httpx

import config

log = logging.getLogger(__name__)
_limit = asyncio.Semaphore(3)       # katta guruhlarda bepul API limitiga urilmaslik uchun

PROMPT = (
    "Sen O'zbekistondagi taksi Telegram guruhlari xabarlarini tasniflaysan. "
    "Xabar o'zbek (lotin/kirill) yoki rus tilida bo'lishi mumkin.\n"
    "label: 'passenger' — odam taksi/mashina qidiryapti yoki pochta jo'natmoqchi; "
    "'driver' — haydovchi yo'lovchi qidiryapti; 'other' — reklama, savol, boshqa.\n"
    'Faqat JSON qaytar: {"label": "...", "from": shahar|null, "to": shahar|null, '
    '"seats": son|null, "time": matn|null}'
)


def _text(v) -> str | None:
    return v.strip()[:60] or None if isinstance(v, str) else None


def _seats(v) -> int | None:
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8 else None


def clean(data) -> dict | None:
    """AI javobiga ishonib bo'lmaydi: faqat kutilgan tur va qiymatlar o'tadi."""
    if not isinstance(data, dict):
        return None
    label = data.get("label")
    return {
        "label": label if label in ("passenger", "driver", "other") else "unknown",
        "from": _text(data.get("from")), "to": _text(data.get("to")),
        "seats": _seats(data.get("seats")), "time": _text(data.get("time")),
    }


async def classify(text: str) -> dict | None:
    if not config.AI_API_KEY:
        return None
    try:
        async with _limit, httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{config.AI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.AI_API_KEY}"},
                json={
                    "model": config.AI_MODEL,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": PROMPT},
                        {"role": "user", "content": text[:800]},
                    ],
                },
            )
            r.raise_for_status()
            return clean(json.loads(r.json()["choices"][0]["message"]["content"]))
    except Exception as e:  # AI ishlamasa bot to'xtamasin
        log.warning("AI xatosi: %s", e)
        return None
