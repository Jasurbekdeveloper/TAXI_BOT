"""Haydovchi akkauntini bot ichida ulash: telefon -> kod -> (2FA parol) -> shifrlangan sessiya.

Telethon StringSession ishlatiladi (Pyrogram'dagi export_session_string() ning muqobili).
Kirish tugagach client uzilmaydi — to'g'ridan-to'g'ri services.broadcaster.manager ga topshiriladi.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass

import config
from database import crud
from services import crypto
from services.broadcaster import manager

log = logging.getLogger(__name__)
PENDING_TTL = 600           # kod kiritilmasa 10 daqiqada bekor qilinadi


@dataclass
class Pending:
    client: object
    phone: str
    code_hash: str
    created: float


_pending: dict[int, Pending] = {}


def new_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(), config.API_ID, config.API_HASH)


client_factory = new_client     # testlarda almashtiriladi


def normalize_phone(text: str) -> str | None:
    """+998 90 123 45 67 / 998901234567 / 901234567 -> +998901234567. Boshqa davlat raqami ham qabul qilinadi."""
    d = re.sub(r"\D", "", text or "")
    if len(d) == 9:
        d = "998" + d
    if 10 <= len(d) <= 15:
        return "+" + d
    return None


def clean_code(text: str) -> str:
    """'1 2 3 4 5', '1-2-3-4-5' -> '12345'."""
    return re.sub(r"\D", "", text or "")


async def _cleanup():
    now = time.time()
    for uid in [u for u, p in _pending.items() if now - p.created > PENDING_TTL]:
        await cancel(uid)


async def send_code(uid: int, phone: str) -> str:
    """Kod yuboradi. Natija: 'ok', 'no_api', 'invalid_phone', 'banned', 'flood:<s>', 'error:<matn>'."""
    if not (config.API_ID and config.API_HASH):
        return "no_api"
    await _cleanup()
    await cancel(uid)
    client = client_factory()
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as e:
        await _disconnect(client)
        n = type(e).__name__
        if n == "PhoneNumberInvalidError":
            return "invalid_phone"
        if n == "PhoneNumberBannedError":
            return "banned"
        if n in ("FloodWaitError", "PhoneNumberFloodError"):
            return f"flood:{getattr(e, 'seconds', 0)}"
        log.warning("Kod yuborilmadi user=%s: %s", uid, e)
        return f"error:{e}"
    _pending[uid] = Pending(client, phone, sent.phone_code_hash, time.time())
    return "ok"


async def submit_code(uid: int, code: str) -> str:
    """Natija: 'ok', 'password' (2FA kerak), 'invalid', 'expired', 'no_pending', 'error:<matn>'."""
    p = _pending.get(uid)
    if p is None:
        return "no_pending"
    try:
        await p.client.sign_in(phone=p.phone, code=code, phone_code_hash=p.code_hash)
    except Exception as e:
        n = type(e).__name__
        if n == "SessionPasswordNeededError":
            return "password"
        if n == "PhoneCodeInvalidError":
            return "invalid"
        if n == "PhoneCodeExpiredError":
            await cancel(uid)
            return "expired"
        log.warning("Kod bilan kirib bo'lmadi user=%s: %s", uid, e)
        await cancel(uid)
        return f"error:{e}"
    return await _finish(uid)


async def submit_password(uid: int, password: str) -> str:
    """Natija: 'ok', 'invalid', 'no_pending', 'error:<matn>'."""
    p = _pending.get(uid)
    if p is None:
        return "no_pending"
    try:
        await p.client.sign_in(password=password)
    except Exception as e:
        if type(e).__name__ == "PasswordHashInvalidError":
            return "invalid"
        log.warning("2FA bilan kirib bo'lmadi user=%s: %s", uid, e)
        await cancel(uid)
        return f"error:{e}"
    return await _finish(uid)


async def _finish(uid: int) -> str:
    p = _pending.pop(uid)
    client = p.client
    try:
        me = await client.get_me()
        session_str = client.session.save()
        name = " ".join(x for x in (me.first_name, me.last_name) if x)
        crud.save_session(uid, p.phone, crypto.encrypt(session_str), me.id, me.username, name)
        await manager.connect(uid, client, authorized=True)
    except Exception as e:
        log.exception("Sessiyani saqlab bo'lmadi user=%s", uid)
        await _disconnect(client)
        return f"error:{e}"
    log.info("Haydovchi akkaunti ulandi user=%s tg=%s", uid, me.id)
    return "ok"


async def cancel(uid: int):
    p = _pending.pop(uid, None)
    if p is not None:
        await _disconnect(p.client)


async def _disconnect(client):
    try:
        await asyncio.wait_for(client.disconnect(), 10)
    except Exception:
        pass


def is_pending(uid: int) -> bool:
    return uid in _pending
