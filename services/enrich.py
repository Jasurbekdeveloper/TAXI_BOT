"""E'lon kelgan ZAHOTI mijoz haqida bor ma'lumotni yig'ish: Telegram username, profil raqami, ism.

Faqat «arzon» usullar (bitta users.getUsers so'rovi): xabarni o'qigan akkaunt mijozni allaqachon taniydi.
Telefon raqami orqali qidirish (kontakt import) bu yerda QILINMAYDI — u ban xavfi bor, shuning uchun
faqat haydovchi «🤖 Bot orqali yozish» ni bosganda ishlaydi (order_contact.resolve_for).
"""
import logging
import time

from telethon.tl.types import InputPeerUser

from nlp import fmt_phone

log = logging.getLogger(__name__)
_cache: dict[int, tuple[float, dict]] = {}
CACHE_TTL = 3600


def _clients_for(owner_id: int | None) -> list:
    """Mijozni ko'rgan akkaunt birinchi, keyin asosiy userbot."""
    import admin
    from services.broadcaster import manager
    out = []
    if owner_id:
        for uid, tg in manager.tg_ids.items():
            if tg == owner_id and uid in manager.clients:
                out.append(manager.clients[uid])
    if admin.userbot is not None and admin.userbot not in out:
        out.append(admin.userbot)
    return out


async def lookup(user_id: int | None, owner_id: int | None = None, access_hash: int | None = None,
                 clients: list | None = None) -> dict:
    """{"username", "phone", "name"} — topilganlari. Topilmasa bo'sh dict."""
    if not user_id or user_id <= 0:
        return {}
    hit = _cache.get(user_id)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    for client in (clients if clients is not None else _clients_for(owner_id)):
        try:
            me = (await client.get_me()).id
            peer = InputPeerUser(user_id, access_hash) if (access_hash is not None and owner_id == me) else user_id
            ent = await client.get_entity(peer)
        except Exception:
            continue
        username = getattr(ent, "username", None) or next(
            (u.username for u in (getattr(ent, "usernames", None) or []) if getattr(u, "active", False)), None)
        name = " ".join(x for x in (getattr(ent, "first_name", None), getattr(ent, "last_name", None)) if x)
        info = {k: v for k, v in (("username", username), ("phone", fmt_phone(getattr(ent, "phone", None))),
                                  ("name", name or None)) if v}
        _cache[user_id] = (time.time(), info)
        if len(_cache) > 5000:
            _cache.pop(next(iter(_cache)))
        return info
    return {}
