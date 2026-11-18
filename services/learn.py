"""Haydovchi/yo'lovchi e'lonlarining belgilarini o'rganib saqlaydi (learned.json).

Maqsad: haydovchilar e'lonni qanday emoji/iconka va takrorlanuvchi so'zlar bilan yozishini eslab qolish —
shunda bir xil uslubdagi e'lon keyingi safar AI'ga YUBORILMAY, mahalliy "haydovchi" deb aniqlanadi
(Groq 429 limitini tejaydi va noto'g'ri e'lon maxfiy guruhga tushmaydi).

Ishlash:
  • learn(matn, label) — ANIQ (kalit so'z) yoki ISHONCHLI AI natijasi bo'lgan har bir xabardan "markerlar"
    (emoji va normallashtirilgan 3+ harfli so'zlar) ajratiladi va label bo'yicha sanaladi.
  • guess(matn) — markerlar yetarlicha ko'p marta DRIVER bilan ko'rilgan bo'lsa (va bir ham kuchli
    yo'lovchi markeri bo'lmasa) — "driver" qaytaradi. Aks holda None. Faqat haydovchi tomoni ishlatiladi:
    noto'g'ri bo'lsa ham yo'lovchi e'loni maxfiy guruhdan qolib ketmasin.
O'z-o'zini o'rgatib xato kuchaymasligi uchun guess natijasi hech qachon qayta o'rganilmaydi (pipeline.process).
"""
import json
import logging
import os
import re

import config
from nlp import normalize

log = logging.getLogger(__name__)

MIN_SEEN = 5        # marker shu martadan kam ko'rilgan bo'lsa, hisobga olinmaydi
RATIO = 3           # driver/passenger nisbati shundan katta bo'lsa — o'sha tomonning markeri
NEED = 3            # shuncha driver markeri topilsa — AI'siz "driver"
SAVE_EVERY = 15     # har shuncha o'rganishdan keyin diskka yoziladi
MAX_TOKENS = 6000   # fayl o'smasligi uchun kam uchraydigan markerlar qisqartiriladi

WORD_RE = re.compile(r"[a-z]{3,}")      # normalize() lotinlashtiradi; 3+ harfli so'zlar

_store: dict[str, dict[str, int]] | None = None
_dirty = 0


def _skip(cp: int) -> bool:
    """Variatsiya selektori, ZWJ, teri rangi, keypad — markerning o'zi emas, bezak."""
    return (0xFE00 <= cp <= 0xFE0F or cp == 0x200D or 0x1F3FB <= cp <= 0x1F3FF
            or 0x20D0 <= cp <= 0x20FF)


def _emojis(raw: str) -> list[str]:
    out = []
    for ch in raw or "":
        cp = ord(ch)
        if cp >= 0x2190 and not ch.isalnum() and not ch.isspace() and not _skip(cp):
            out.append("e:" + ch)
    return out


def _tokens(raw: str) -> set[str]:
    """Xabarning belgilari: emoji + normallashtirilgan so'zlar (har biri bir marta)."""
    toks = set(_emojis(raw))
    toks.update("w:" + w for w in WORD_RE.findall(normalize(raw)))
    return toks


# ---------- saqlash ----------
def _load() -> dict:
    global _store
    if _store is None:
        _store = {"driver": {}, "passenger": {}}
        try:
            if config.LEARN_FILE.exists():
                data = json.loads(config.LEARN_FILE.read_text(encoding="utf-8"))
                for lbl in ("driver", "passenger"):
                    got = data.get(lbl)
                    if isinstance(got, dict):
                        _store[lbl] = {str(k): int(v) for k, v in got.items() if isinstance(v, int)}
        except Exception as e:                      # buzuq fayl botni to'xtatmasin
            log.warning("learned.json o'qilmadi: %s", e)
    return _store


def _prune():
    total = len(_store["driver"]) + len(_store["passenger"])
    if total <= MAX_TOKENS:
        return
    for lbl in ("driver", "passenger"):             # kam uchraganlarni (1 marta) olib tashlaymiz
        _store[lbl] = {k: v for k, v in _store[lbl].items() if v > 1}


def save():
    global _dirty
    if _store is None:
        return
    _prune()
    try:
        tmp = config.LEARN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_store, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, config.LEARN_FILE)          # yozish yarmida uzilsa, eski fayl buzilmaydi
        _dirty = 0
    except Exception as e:
        log.warning("learned.json yozilmadi: %s", e)


# ---------- o'rganish / taxmin ----------
def learn(raw: str, label: str):
    if label not in ("driver", "passenger") or not (raw or "").strip():
        return
    global _dirty
    bucket = _load()[label]
    for tok in _tokens(raw):
        bucket[tok] = bucket.get(tok, 0) + 1
    _dirty += 1
    if _dirty >= SAVE_EVERY:
        save()


def guess(raw: str) -> str | None:
    """O'rganilgan belgilarga ko'ra "driver" yoki None (hech qachon "passenger" qaytarmaydi)."""
    store = _load()
    drv, psn = store["driver"], store["passenger"]
    d_hits = p_hits = 0
    for tok in _tokens(raw):
        d, p = drv.get(tok, 0), psn.get(tok, 0)
        if d + p < MIN_SEEN:
            continue
        if d >= MIN_SEEN and d >= RATIO * p:
            d_hits += 1
        elif p >= MIN_SEEN and p >= RATIO * d:
            p_hits += 1
    return "driver" if d_hits >= NEED and p_hits == 0 else None


def reset():                                        # testlar uchun
    global _store, _dirty
    _store, _dirty = None, 0
