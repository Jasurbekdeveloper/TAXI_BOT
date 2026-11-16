"""Haydovchi sessiyalarini shifrlash (cryptography.fernet).

Kalit .env dagi SESSION_SECRET dan olinadi. Bo'lmasa fernet.key fayli bir marta yaratiladi.
DIQQAT: kalit yo'qolsa, saqlangan barcha sessiyalar ochilmaydi — haydovchilar qayta ulanishi kerak bo'ladi.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

import config

log = logging.getLogger(__name__)
_fernet: Fernet | None = None


def _key() -> bytes:
    if config.SESSION_SECRET:
        return config.SESSION_SECRET.encode()
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


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


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
