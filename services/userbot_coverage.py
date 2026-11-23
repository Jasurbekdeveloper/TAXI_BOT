"""Asosiy userbot haydovchilar tanlagan guruhlarga va donor guruhlarga avtomatik a'zo bo'ladi.

Nega kerak: username'siz yo'lovchiga yozish uchun akkaunt uni umumiy guruhda «ko'rgan» bo'lishi shart.
E'lonni haydovchi A ning akkaunti o'qisa-yu, «💬 Yozish» ni haydovchi B bossa — B ham, userbot ham
mijozni tanimaydi. Userbot hamma manba guruhlarda o'tirsa, u har doim zaxira sifatida yoza oladi.

Faqat ochiq (username'li) guruhlarga qo'shiladi. Yopiq guruhga taklif havolasiz kirib bo'lmaydi —
ular logda «yopiq guruh» deb ko'rsatiladi, ularga userbotni qo'lda qo'shish kerak.
Anti-ban: bir aylanishda ko'pi bilan JOIN_PER_RUN ta, har biri orasida JOIN_GAP soniya.
"""
import asyncio
import logging
import random

from telethon.errors import (ChannelPrivateError, ChannelsTooMuchError, FloodWaitError, InviteRequestSentError,
                             UserBannedInChannelError)
from telethon.tl.functions.channels import JoinChannelRequest

from database import crud

log = logging.getLogger(__name__)

RUN_EVERY = 30 * 60          # har 30 daqiqada tekshiradi (haydovchilar yangi guruh tanlashi mumkin)
JOIN_PER_RUN = 5             # bir aylanishda ko'pi bilan shuncha guruhga qo'shiladi
JOIN_GAP = (60, 120)         # qo'shilishlar orasidagi tasodifiy pauza (soniya)

_failed: set[int] = set()    # qo'shilib bo'lmaydigan (yopiq/ban) guruhlar — qayta urinilmaydi
status: dict = {"joined": 0, "private": [], "last_run": None}


async def _member_ids(client) -> set[int]:
    ids = set()
    async for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            ids.add(d.id)
    return ids


async def _username_of(chat_id: int, readers: list) -> tuple[str | None, str]:
    """Guruh username'ini shu guruhni o'qiyotgan haydovchi akkaunti orqali aniqlaydi."""
    for client in readers:
        try:
            ent = await client.get_entity(chat_id)
            return getattr(ent, "username", None), getattr(ent, "title", "") or str(chat_id)
        except Exception:
            continue
    return None, str(chat_id)


def _targets() -> dict[int, list[int]]:
    """{chat_id: [shu guruhni tanlagan haydovchilar (bot uid)]} + donor guruhlar."""
    out: dict[int, list[int]] = {}
    for uid, chats in crud.all_selected_chat_ids().items():
        for cid in chats:
            out.setdefault(cid, []).append(uid)
    for d in crud.all_donors():
        if d["enabled"]:
            out.setdefault(d["chat_id"], [])
    return out


async def run_once(client, manager) -> dict:
    mine = await _member_ids(client)
    missing = {cid: uids for cid, uids in _targets().items() if cid not in mine and cid not in _failed}
    joined, private = 0, []
    for cid, uids in missing.items():
        if joined >= JOIN_PER_RUN:
            break
        readers = [manager.clients[u] for u in uids if u in manager.clients] or list(manager.clients.values())
        username, title = await _username_of(cid, readers)
        if not username and uids:       # akkauntlar endi doim ulanmaydi: guruhni tanlagan haydovchi orqali qisqa ulanib
            async with manager.session(uids[0]) as drv:
                if drv is not None:
                    username, title = await _username_of(cid, [drv])
        if not username:
            private.append(title)
            _failed.add(cid)
            continue
        try:
            await client(JoinChannelRequest(username))
            joined += 1
            log.info("[coverage] userbot guruhga qo'shildi: %s (@%s)", title, username)
            await asyncio.sleep(random.uniform(*JOIN_GAP))
        except FloodWaitError as e:
            log.warning("[coverage] FloodWait %s s — keyingi aylanishda davom etadi", e.seconds)
            break
        except InviteRequestSentError:
            log.info("[coverage] %s: qo'shilish so'rovi yuborildi (admin tasdiqlashi kerak)", title)
            _failed.add(cid)
        except ChannelsTooMuchError:
            log.error("[coverage] userbot guruhlar limitiga yetdi (500). Keraksizlaridan chiqing")
            break
        except (ChannelPrivateError, UserBannedInChannelError) as e:
            log.info("[coverage] %s: qo'shilib bo'lmadi (%s)", title, type(e).__name__)
            _failed.add(cid)
        except Exception as e:
            log.warning("[coverage] %s: %s", title, str(e)[:90])
    log.info("[coverage] tekshirildi: kerakli %s ta, yetishmagan %s ta, qo'shildi %s ta",
             len(_targets()), len(missing), joined)
    if private:
        log.info("[coverage] yopiq guruhlar (userbotni qo'lda qo'shing): %s", ", ".join(private[:10]))
    status.update(joined=status["joined"] + joined, private=private, last_run=asyncio.get_running_loop().time())
    return {"joined": joined, "private": private, "missing": len(missing)}


async def loop(client, manager):
    await asyncio.sleep(60)                  # ishga tushgandan keyin haydovchi akkauntlari ulanib olsin
    while True:
        try:
            await run_once(client, manager)
        except Exception as e:
            log.error("[coverage] xato: %s", e)
        await asyncio.sleep(RUN_EVERY)
