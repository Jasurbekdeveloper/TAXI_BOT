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

# Hamma uchun bir xil: mention «Lichkaga yozish» so'ziga qo'yiladi (ism «.» yoki □□□ bo'lsa ham chiroyli)
LINK_TEXT = "Lichkaga yozish"
TEXT = "💬 " + LINK_TEXT + "  ← bosing, mijoz profili ochiladi"
_dialogs_loaded = {"ok": False}


_send_as_ok: dict[int, bool] = {}           # chat_id -> guruh nomidan yozish mumkinmi (bir marta aniqlanadi)


_SEND_AS_RIGHTS_ERRORS = ("ChatAdminRequiredError", "SendAsPeerInvalidError", "ChatSendPlainForbiddenError",
                          "UserBannedInChannelError", "ChatWriteForbiddenError")


def _has_mention(msg) -> bool:
    return msg is not None and any(isinstance(e, MessageEntityMentionName) for e in (msg.entities or []))


async def _send(client, chat_id: int, text: str, reply_to: int, ent):
    """Avval GURUH NOMIDAN (send_as) yuboradi. Agar huquq bo'lmasa YOKI Telegram guruh nomidan yuborilgan
    xabardagi mention'ni olib tashlasa — userbot nomidan qayta yuboradi (mention ishlashi muhimroq).
    Guruh nomidan mention olib tashlansa, shu guruh uchun keyingi safar to'g'ridan-to'g'ri userbot nomidan."""
    from telethon.tl.functions.messages import SendMessageRequest
    from telethon.tl.types import InputReplyToMessage
    peer = await client.get_input_entity(chat_id)
    if _send_as_ok.get(chat_id, True):
        req = SendMessageRequest(peer=peer, message=text, no_webpage=True, entities=[ent],
                                 reply_to=InputReplyToMessage(reply_to_msg_id=reply_to),
                                 random_id=random.randrange(-2 ** 63, 2 ** 63), send_as=peer)
        try:
            res = await client(req)
            msg = client._get_response_message(req, res, peer)
            if _has_mention(msg):
                return msg
            # Telegram guruh nomidan xabarda mijozga ishorani olib tashladi — userbot nomidan urinamiz
            _send_as_ok[chat_id] = False
            log.warning("[mention] guruh nomidan yuborilganda Telegram mention'ni olib tashladi (chat=%s) — "
                        "bundan keyin bu guruhda userbot nomidan yoziladi", chat_id)
            try:
                if msg is not None:
                    await msg.delete()
            except Exception:
                pass
        except Exception as e:
            n = type(e).__name__
            if n == "FloodWaitError":
                raise
            if n in _SEND_AS_RIGHTS_ERRORS:     # faqat huquq xatosida eslab qolamiz
                _send_as_ok[chat_id] = False
                log.warning("[mention] guruh nomidan yozib bo'lmadi (chat=%s): %s. Userbotni yopiq guruhda admin "
                            "qiling va «Anonim qolish» huquqini yoqing. Hozircha userbot nomidan yoziladi.", chat_id, n)
            else:                               # boshqa xato (masalan, yaroqsiz ishora) — keyingi usulga
                raise
    return await client.send_message(chat_id, text, reply_to=reply_to, formatting_entities=[ent],
                                      link_preview=False)


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


_member_cache = {"ids": set(), "ts": 0.0}


async def _chat_peer(client, chat_id: int):
    """Guruhning InputPeer'i. Telethon guruhni faqat keshida bo'lsa topadi — userbot a'zo bo'lsa ham kesh
    bo'sh bo'lishi mumkin. Shuning uchun topilmasa dialoglar ro'yxatini yangilaymiz (10 daqiqada bir marta)."""
    import time
    try:
        return await client.get_input_entity(chat_id)
    except Exception:
        pass
    if time.time() - _member_cache["ts"] > 600:
        _member_cache["ts"] = time.time()
        ids = set()
        async for d in client.iter_dialogs():
            ids.add(d.id)
        _member_cache["ids"] = ids
        log.info("[mention] userbot dialoglari yangilandi: %s ta", len(ids))
    if chat_id not in _member_cache["ids"]:
        log.info("[mention] userbot manba guruhga A'ZO EMAS: %s", chat_id)
        return None
    try:
        return await client.get_input_entity(chat_id)
    except Exception as e:
        log.info("[mention] manba guruh topilmadi (%s): %s", chat_id, str(e)[:80])
        return None


async def _candidates(client, info: dict) -> list:
    """Mijozga ishora qilishning bir necha usuli. Katta guruhlarda yuboruvchi ko'pincha «min» bo'ladi:
    uning access_hash i boshqa joyda yaroqsiz va Telegram mention'ni JIM olib tashlaydi.
    Shuning uchun avval «xabar orqali» (InputUserFromMessage) — asl xabarni userbot o'zi o'qigan bo'lsa ishonchli."""
    me = (await client.get_me()).id
    uid = info["user_id"]
    out = []
    # Xabarni haydovchi akkaunti o'qigan bo'lsa ham ishlaydi — faqat userbot ham o'sha guruhda bo'lsa kifoya
    if info.get("src_chat") and info.get("src_msg"):
        peer = await _chat_peer(client, info["src_chat"])
        if peer is not None:
            from_msg = InputUserFromMessage(peer=peer, msg_id=info["src_msg"], user_id=uid)
            # «Xabar orqali» havolani to'liq foydalanuvchiga aylantiramiz: users.getUsers shu akkaunt uchun
            # yaroqli access_hash qaytaradi. Mention'ga aynan shu kerak (from_msg ni Telegram olib tashlaydi).
            try:
                from telethon.tl.functions.users import GetUsersRequest
                res = await client(GetUsersRequest([from_msg]))
                u = res[0] if res else None
                if u is not None and getattr(u, "access_hash", None) and not getattr(u, "min", False):
                    out.append(InputUser(u.id, u.access_hash))
            except Exception as e:
                log.info("[mention] getUsers(xabar orqali) ishlamadi: %s", str(e)[:80])
            # Zaxira: asl xabarni o'qib olsak, Telethon mijozni keshga yozadi
            if not out:
                try:
                    await client.get_messages(peer, ids=info["src_msg"])
                    p2 = await client.get_input_entity(uid)
                    if isinstance(p2, InputPeerUser):
                        out.append(InputUser(p2.user_id, p2.access_hash))
                except Exception as e:
                    log.info("[mention] asl xabar orqali ham topilmadi: %s", str(e)[:80])
            out.append(from_msg)
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
    from services.card import clean_name
    name = clean_name(info.get("name"))
    text = TEXT + (f"\n👤 {name}" if name else "")
    start = text.index(LINK_TEXT)
    off, ln = _u16(text[:start]), _u16(LINK_TEXT)
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
            if _has_mention(msg):
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
