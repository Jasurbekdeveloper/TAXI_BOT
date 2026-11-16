"""Yo'nalishlar va Smart Routing. Ma'lumot SQLite `routes` jadvalida (database/crud.py).

Yo'nalish — ikki shaharning tartibsiz juftligi (Termiz-Toshkent = Toshkent-Termiz) va unga
biriktirilgan yopiq guruh (chat_id). chat_id bo'sh bo'lsa e'lon DRIVERS_CHAT_ID ga boradi.
Ro'yxat bo'sh bo'lsa, hamma yo'nalish o'tadi va hammasi DRIVERS_CHAT_ID ga boradi.
"""
import re

import config
from database import crud
from nlp import canon_city, known_city


def all_routes() -> list[list[str]]:
    return [[r["city_a"], r["city_b"]] for r in crud.all_routes()]


def _find(ca: str, cb: str):
    pair = {ca, cb}
    return next((r for r in crud.all_routes() if {r["city_a"], r["city_b"]} == pair), None)


def add(a: str, b: str, chat_id: int | None = None, title: str = "") -> bool:
    """Ikki shahar nomini qabul qiladi (kanonik ko'rinishga keltiradi). Yangi bo'lsa True."""
    if not (known_city(a) and known_city(b)):   # faqat tanilgan shaharlar
        return False
    ca, cb = canon_city(a), canon_city(b)
    if ca == cb or _find(ca, cb):
        return False
    crud.add_route(ca, cb, chat_id, title)
    return True


def remove(a: str, b: str) -> bool:
    r = _find(canon_city(a), canon_city(b))
    return bool(r) and crud.delete_route(r["id"])


def parse_pair(text: str) -> tuple[str, str] | None:
    """"Termiz-Toshkent", "Termiz Toshkent", "Termiz → Toshkent" -> (frm, to) yoki None."""
    parts = [p for p in re.split(r"[-–—>→,\s]+", text.strip()) if p]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def allowed(frm: str | None, to: str | None) -> bool:
    """Shu yo'nalish yopiq guruhlarga yuborilsinmi?"""
    rs = crud.all_routes()
    if not rs:                          # ro'yxat bo'sh: hammasi o'tadi
        return True
    if not (frm and to):                # yo'nalish noaniq
        return not config.ROUTE_FILTER_STRICT
    return _find(frm, to) is not None


def target_chat(frm: str | None, to: str | None) -> int:
    """E'lon qaysi yopiq guruhga ketadi. Yo'nalishga guruh biriktirilmagan bo'lsa — DRIVERS_CHAT_ID."""
    r = _find(frm, to) if frm and to else None
    return r["chat_id"] if r is not None and r["chat_id"] else config.DRIVERS_CHAT_ID


def closed_chat_ids() -> set[int]:
    """Barcha yopiq (e'lon qabul qiluvchi) guruhlar: ular manba sifatida o'qilmaydi va ularga tarqatilmaydi."""
    ids = {r["chat_id"] for r in crud.all_routes() if r["chat_id"]}
    if config.DRIVERS_CHAT_ID:
        ids.add(config.DRIVERS_CHAT_ID)
    return ids
