"""Haydovchi sessiyalarini shifrlash (cryptography.fernet).

Kalit .env dagi SESSION_SECRET dan olinadi. Bo'lmasa fernet.key fayli bir marta yaratiladi.
Kalitni almashtirish (rotatsiya): SESSION_SECRET=yangi_kalit,eski_kalit — birinchisi bilan shifrlanadi, hammasi
bilan ochiladi. Bot ishga tushganda barcha sessiyalar yangi kalitga qayta shifrlanadi (rotate_all), keyin eski
kalitni .env dan olib tashlash mumkin.
DIQQAT: kalit yo'qolsa, saqlangan barcha sessiyalar ochilmaydi — haydovchilar qayta ulanishi kerak bo'ladi.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

import config

log = logging.getLogger(__name__)
_fernet: MultiFernet | None = None


def _keys() -> list[bytes]:
    if config.SESSION_SECRET:
        return [k.strip().encode() for k in config.SESSION_SECRET.split(",") if k.strip()]
    return [_key()]


def _key() -> bytes:
    path = config.FERNET_KEY_FILE
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    log.warning("SESSION_SECRET berilmagan: yangi kalit %s ga yozildi. Uni zaxiralang!", path.name)
    return key


def fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        _fernet = MultiFernet([Fernet(k) for k in _keys()])
    return _fernet


def key_source() -> str:
    return "env" if config.SESSION_SECRET else "file"


def rotate_all() -> int:
    """Barcha haydovchi sessiyalarini joriy (birinchi) kalit bilan qayta shifrlaydi. Nechta yangilandi."""
    from database import models
    c = models.conn()
    n = 0
    for row in c.execute("SELECT user_id, session_enc FROM user_sessions").fetchall():
        try:
            new = fernet().rotate(row["session_enc"].encode()).decode()
        except (InvalidToken, ValueError):
            continue
        if new != row["session_enc"]:
            c.execute("UPDATE user_sessions SET session_enc=? WHERE user_id=?", (new, row["user_id"]))
            n += 1
    return n


def encrypt(text: str) -> str:
    return fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    """Ochib bo'lmasa (kalit almashgan) None."""
    try:
        return fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def reset():
    """Testlar uchun."""
    global _fernet
    _fernet = None
