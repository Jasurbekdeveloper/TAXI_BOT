"""Username'siz yo'lovchi uchun QO'SHIMCHA qatlam: bot e'lonni yuborgach, userbot shu e'longa reply qilib
mijozga «mention» qo'yadi. Mention Telegram'da mijoz profilini xabarga biriktiradi — yopiq guruhdagi har bir
haydovchi ismga bosib lichkani ochadi va o'zi yozadi (username bo'lmasa ham).

Faqat yo'lovchi o'zi yozgan xabar (donor / qayta joylangan emas) va username yo'q bo'lganda (pipeline.process).
Userbot mijozni allaqachon taniydigan bo'lishi kerak: hech qanday qidiruv/telefon import QILINMAYDI.
Tanimasa yoki userbot ishlamasa — jim o'tkazib yuboriladi, botning e'loniga ta'sir qilmaydi.
"""
import logging

from telethon.tl.types import InputMessageEntityMentionName, InputPeerUser, InputUser

log = logging.getLogger(__name__)

TEXT = "👤 Mijoz lichkasi: {name}\nIsmiga bosing — profil ochiladi, o'zingiz yozasiz."
_dialogs_loaded = {"ok": False}


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


async def _input_user(client, info: dict):
    me = (await client.get_me()).id
    uid = info["user_id"]
    if info.get("access_hash") is not None and info.get("owner_id") == me:
        return InputUser(uid, info["access_hash"])
    peer = await client.get_input_entity(uid)          # sessiya keshi (userbot o'zi ko'rgan bo'lsa)
    if isinstance(peer, InputPeerUser):
        return InputUser(peer.user_id, peer.access_hash)
    return None


async def send(chat_id: int, reply_to: int, info: dict):
    import admin
    client = admin.userbot
    if client is None:
        return
    try:
        user = await _input_user(client, info)
    except Exception as e:
        log.info("[mention] userbot mijozni tanimaydi (uid=%s): %s", info.get("user_id"), str(e)[:80])
        return
    if user is None:
        return
    name = (info.get("name") or "Mijoz").strip()[:40] or "Mijoz"
    text = TEXT.format(name=name)
    start = text.index(name)
    ent = InputMessageEntityMentionName(offset=_u16(text[:start]), length=_u16(name), user_id=user)
    for attempt in (1, 2):
        try:
            await client.send_message(chat_id, text, reply_to=reply_to, formatting_entities=[ent],
                                      link_preview=False)
            log.info("[mention] → %s | uid=%s", chat_id, info["user_id"])
            return
        except ValueError:                              # yopiq guruh userbot keshida yo'q: dialoglarni yuklaymiz
            if attempt == 1 and not _dialogs_loaded["ok"]:
                _dialogs_loaded["ok"] = True
                await client.get_dialogs(limit=300)
                continue
            log.info("[mention] userbot yopiq guruhni topmadi (chat=%s) — u guruhga a'zomi?", chat_id)
            return
        except Exception as e:
            log.info("[mention] yuborilmadi (chat=%s): %s", chat_id, str(e)[:100])
            return
