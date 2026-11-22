"""Username'siz yo'lovchi uchun QO'SHIMCHA qatlam: bot e'lonni yuborgach, userbot shu e'longa reply qilib
mijozga «mention» qo'yadi. Mention Telegram'da mijoz profilini xabarga biriktiradi — yopiq guruhdagi har bir
haydovchi ismga bosib lichkani ochadi va o'zi yozadi (username bo'lmasa ham).

Faqat yo'lovchi o'zi yozgan xabar (donor / qayta joylangan emas) va username yo'q bo'lganda (pipeline.process).
Userbot mijozni allaqachon taniydigan bo'lishi kerak: hech qanday qidiruv/telefon import QILINMAYDI.
Tanimasa yoki userbot ishlamasa — jim o'tkazib yuboriladi, botning e'loniga ta'sir qilmaydi.
"""
import logging
import random

from telethon.tl.types import (InputMessageEntityMentionName, InputPeerUser, InputUser, InputUserFromMessage,
                               MessageEntityMentionName)

log = logging.getLogger(__name__)

TEXT = "👤 Mijoz lichkasi: {name}\nIsmiga bosing — profil ochiladi, o'zingiz yozasiz."
_dialogs_loaded = {"ok": False}


_send_as_ok: dict[int, bool] = {}           # chat_id -> guruh nomidan yozish mumkinmi (bir marta aniqlanadi)


async def _send(client, chat_id: int, text: str, reply_to: int, ent):
    """GURUH NOMIDAN (send_as = guruhning o'zi) yuboradi. Buning uchun userbot yopiq guruhda admin va
    «Anonim qolish» huquqi yoqilgan bo'lishi kerak. Bo'lmasa — userbot nomidan (zaxira), logda ogohlantirish."""
    from telethon.tl.functions.messages import SendMessageRequest
    from telethon.tl.types import InputReplyToMessage
    peer = await client.get_input_entity(chat_id)
    if _send_as_ok.get(chat_id, True):
        req = SendMessageRequest(peer=peer, message=text, no_webpage=True, entities=[ent],
                                 reply_to=InputReplyToMessage(reply_to_msg_id=reply_to),
                                 random_id=random.randrange(-2 ** 63, 2 ** 63), send_as=peer)
        try:
            res = await client(req)
            _send_as_ok[chat_id] = True
            return client._get_response_message(req, res, peer)
        except Exception as e:
            if type(e).__name__ in ("FloodWaitError",):
                raise
            _send_as_ok[chat_id] = False
            log.warning("[mention] guruh nomidan yozib bo'lmadi (chat=%s): %s. Userbotni yopiq guruhda admin "
                        "qiling va «Anonim qolish» huquqini yoqing. Hozircha userbot nomidan yoziladi.",
                        chat_id, type(e).__name__)
    return await client.send_message(chat_id, text, reply_to=reply_to, formatting_entities=[ent],
                                      link_preview=False)


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


async def _candidates(client, info: dict) -> list:
    """Mijozga ishora qilishning bir necha usuli. Katta guruhlarda yuboruvchi ko'pincha «min» bo'ladi:
    uning access_hash i boshqa joyda yaroqsiz va Telegram mention'ni JIM olib tashlaydi.
    Shuning uchun avval «xabar orqali» (InputUserFromMessage) — asl xabarni userbot o'zi o'qigan bo'lsa ishonchli."""
    me = (await client.get_me()).id
    uid = info["user_id"]
    out = []
    # Xabarni haydovchi akkaunti o'qigan bo'lsa ham ishlaydi — faqat userbot ham o'sha guruhda bo'lsa kifoya
    if info.get("src_chat") and info.get("src_msg"):
        try:
            peer = await client.get_input_entity(info["src_chat"])
            out.append(InputUserFromMessage(peer=peer, msg_id=info["src_msg"], user_id=uid))
        except Exception:
            pass
    if info.get("access_hash") is not None and info.get("owner_id") == me:
        out.append(InputUser(uid, info["access_hash"]))
    try:
        peer = await client.get_input_entity(uid)      # sessiya keshi (userbot o'zi ko'rgan bo'lsa)
        if isinstance(peer, InputPeerUser):
            out.append(InputUser(peer.user_id, peer.access_hash))
    except Exception:
        pass
    return out


async def send(chat_id: int, reply_to: int, info: dict):
    import admin
    client = admin.userbot
    if client is None:
        return
    try:
        users = await _candidates(client, info)
    except Exception as e:
        log.info("[mention] mijoz aniqlanmadi (uid=%s): %s", info.get("user_id"), str(e)[:80])
        return
    if not users:
        log.info("[mention] userbot mijozni tanimaydi (uid=%s, manba=%s) — userbot shu manba guruhga a'zomi?",
                 info.get("user_id"), info.get("src_chat"))
        return
    name = (info.get("name") or "Mijoz").strip()[:40] or "Mijoz"
    text = TEXT.format(name=name)
    start = text.index(name)
    off, ln = _u16(text[:start]), _u16(name)
    for user in users:
        ent = InputMessageEntityMentionName(offset=off, length=ln, user_id=user)
        for attempt in (1, 2):
            try:
                msg = await _send(client, chat_id, text, reply_to, ent)
            except ValueError:                          # yopiq guruh userbot keshida yo'q: dialoglarni yuklaymiz
                if attempt == 1 and not _dialogs_loaded["ok"]:
                    _dialogs_loaded["ok"] = True
                    await client.get_dialogs(limit=300)
                    continue
                log.info("[mention] userbot yopiq guruhni topmadi (chat=%s) — u guruhga a'zomi?", chat_id)
                return
            except Exception as e:
                log.info("[mention] %s bilan yuborilmadi: %s", type(user).__name__, str(e)[:100])
                break                                   # keyingi usulni sinaymiz
            # Telegram yaroqsiz mention'ni xatosiz olib tashlaydi — natijada bor-yo'qligini tekshiramiz
            if msg is not None and any(isinstance(e, MessageEntityMentionName) for e in (msg.entities or [])):
                log.info("[mention] → %s | uid=%s (%s)", chat_id, info["user_id"], type(user).__name__)
                return
            log.info("[mention] Telegram mention'ni olib tashladi (%s) — keyingi usul", type(user).__name__)
            try:
                if msg is not None:
                    await msg.delete()
            except Exception:
                pass
            break
    log.info("[mention] hech bir usul ishlamadi (uid=%s)", info.get("user_id"))
