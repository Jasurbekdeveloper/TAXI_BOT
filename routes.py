"""Xizmat qilinadigan yo'nalishlar ro'yxati. routes.json da saqlanadi (store.py atomik-JSON naqshi).

Yo'nalish — ikki shaharning tartibsiz juftligi (Termiz-Toshkent = Toshkent-Termiz).
Ro'yxat bo'sh bo'lsa, hamma yo'nalish o'tadi (orqaga moslik).
"""
import json
import logging
import os
import re

import config
from nlp import canon_city, known_city

log = logging.getLogger(__name__)

_routes: list[list[str]] | None = None      # [[CityA, CityB], ...]


def _load() -> list[list[str]]:
    global _routes
    if _routes is None:
        try:
            _routes = json.loads(config.ROUTES_FILE.read_text(encoding="utf-8")) if config.ROUTES_FILE.exists() else []
        except (OSError, ValueError) as e:
            log.error("%s o'qilmadi (%s)", config.ROUTES_FILE.name, e)
            _routes = []
    return _routes


def _save():
    tmp = config.ROUTES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_routes, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, config.ROUTES_FILE)


def all_routes() -> list[list[str]]:
    return [list(r) for r in _load()]


def add(a: str, b: str) -> bool:
    """Ikki shahar nomini qabul qiladi (kanonik ko'rinishga keltiradi). Yangi bo'lsa True."""
    if not (known_city(a) and known_city(b)):   # faqat tanilgan shaharlar
        return False
    ca, cb = canon_city(a), canon_city(b)
    if ca == cb:
        return False
    pair = {ca, cb}
    routes = _load()
    if any(pair == set(r) for r in routes):
        return False
    routes.append([ca, cb])
    _save()
    return True


def remove(a: str, b: str) -> bool:
    ca, cb = canon_city(a), canon_city(b)
    pair = {ca, cb}
    routes = _load()
    kept = [r for r in routes if set(r) != pair]
    if len(kept) == len(routes):
        return False
    routes[:] = kept
    _save()
    return True


def parse_pair(text: str) -> tuple[str, str] | None:
    """"Termiz-Toshkent", "Termiz Toshkent", "Termiz → Toshkent" -> (frm, to) yoki None."""
    parts = [p for p in re.split(r"[-–—>→,\s]+", text.strip()) if p]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def allowed(frm: str | None, to: str | None) -> bool:
    """Shu yo'nalish maxfiy guruhga yuborilsinmi?"""
    routes = _load()
    if not routes:                      # ro'yxat bo'sh: hammasi o'tadi
        return True
    if not (frm and to):                # yo'nalish noaniq
        return not config.ROUTE_FILTER_STRICT
    pair = {frm, to}
    return any(pair == set(r) for r in routes)
