"""Username'siz mijozga userbot orqali shaxsiy xabar yuborish (#Order_N tizimi).

Muammo: username yo'q odamga havola (t.me/...) ishlamaydi, tg://user?id=... ko'pincha ochilmaydi.
Yechim: userbot mijozni guruhda ko'rgan zahoti uning user_id + access_hash ini saqlaydi
(faqat username YO'Q bo'lsa va faqat /admin sozlamasidagi order_ttl_hours soatga). Yopiq guruhdagi e'longa
#Order_N qo'yiladi. Haydovchi shu e'longa reply qilsa (yoki #Order_N ni yozsa), userbot
mijozga «haydovchi siz bilan bog'lanmoqchi» deb shaxsiy xabar yuboradi.

Muhim: access_hash har bir AKKAUNT uchun alohida. Shuning uchun xabarni mijozni ko'rgan
o'sha userbot akkaunti yuboradi (owner_id). Boshqa akkaunt bilan yuborib bo'lmaydi.

Ulash (main.py, userbot handler ichida):
    order_no = await order_contact.remember(client, event, sender_)   # username bo'lsa None qaytaradi
    ... e'lon matniga order_contact.tag(order_no) qo'shing (None bo'lsa hech narsa qo'shilmaydi)
    order_contact.register(client, closed_chat_ids=routes.closed_chat_ids)  # bir marta, start'da
"""
import asyncio
import html
import logging
import random
import re
import sqlite3
import time
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import (FloodWaitError, InputUserDeactivatedError, PeerFloodError, PeerIdInvalidError,
                             UserIsBlockedError, UserPrivacyRestrictedError)
from telethon.tl.types import InputPeerUser

import config

log = logging.getLogger(__name__)



def ttl_sec() -> float:
    """Saqlanish muddati: /admin -> ⚙️ Tizim sozlamalari -> order_ttl_hours (har safar bazadan o'qiladi)."""
    try:
        from database import crud
        return crud.get_setting("order_ttl_hours") * 3600
    except Exception:                       # baza yoki sozlama yo'q bo'lsa — 3 soat
        return 3 * 3600


DM_DELAY = (5, 15)                     # har bir shaxsiy xabar oldidan tasodifiy kutish (soniya)
DM_PER_HOUR = 20                       # bitta akkaunt soatiga maksimal shaxsiy xabar (anti-ban)
ORDER_RE = re.compile(r"#Order_(\d+)", re.I)
DB_FILE = Path(getattr(config, "BASE_DIR", Path("."))) / "order_contacts.db"

DM_TEXT = ("Assalomu alaykum! Siz guruhda yozgan e'loningiz bo'yicha haydovchi siz bilan bog'lanmoqchi.\n"
           "🚕 Haydovchi: {driver}\n"
           "Iltimos, ismiga bosib unga yozing.")


# ---------- baza ----------
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, isolation_level=None)
    c.execute("""CREATE TABLE IF NOT EXISTS order_contacts (
        order_no    INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        access_hash INTEGER,
        owner_id    INTEGER NOT NULL,          -- mijozni ko'rgan userbot akkaunti
        name        TEXT,
        created     REAL NOT NULL,
        contacted   INTEGER DEFAULT 0)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_oc_created ON order_contacts(created)")
    return c


_conn = _db()


def purge() -> int:
    """Saqlanish muddatidan (order_ttl_hours) eski yozuvlarni o'chiradi."""
    n = _conn.execute("DELETE FROM order_contacts WHERE created < ?",
                      (time.time() - ttl_sec(),)).rowcount
    if n:
        log.info("order_contacts: %s ta eski yozuv o'chirildi", n)
    return n


async def purge_loop(every_sec: int = 600):
    while True:
        try:
            purge()
        except Exception as e:
            log.error("purge xatosi: %s", e)
        await asyncio.sleep(every_sec)


def tag(order_no: int | None) -> str:
    return f"#Order_{order_no}" if order_no else ""


# ---------- 1. Saqlash ----------
async def remember(client: TelegramClient, event, sender=None) -> int | None:
    """Mijoz username'siz bo'lsa: user_id + access_hash ni saqlaydi va buyurtma raqamini qaytaradi.
    Username bo'lsa yoki saqlab bo'lmasa — None (t.me/username havolasi yetarli)."""
    sender = sender or await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "username", None):
        return None
    access_hash = getattr(sender, "access_hash", None)
    if access_hash is None:                 # min-entity: hash yo'q, input_entity orqali urinib ko'ramiz
        try:
            peer = await client.get_input_entity(sender.id)
            access_hash = getattr(peer, "access_hash", None)
        except (ValueError, PeerIdInvalidError):
            pass
    me = await client.get_me()
    name = " ".join(x for x in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if x)
    return save(sender.id, access_hash, me.id, name)


def save(user_id: int, access_hash: int | None, owner_id: int, name: str | None = None) -> int:
    """Yozuv qo'shadi va #Order raqamini qaytaradi. Shu mijozning muddati o'tmagan yozuvi bo'lsa — o'sha raqam."""
    row = _conn.execute("SELECT order_no FROM order_contacts WHERE user_id=? AND owner_id=? AND created>? "
                        "ORDER BY order_no DESC LIMIT 1", (user_id, owner_id, time.time() - ttl_sec())).fetchone()
    if row:
        _conn.execute("UPDATE order_contacts SET access_hash=COALESCE(?, access_hash), contacted=0 "
                      "WHERE order_no=?", (access_hash, row[0]))
        return row[0]
    cur = _conn.execute(
        "INSERT INTO order_contacts(user_id, access_hash, owner_id, name, created) VALUES (?,?,?,?,?)",
        (user_id, access_hash, owner_id, (name or "")[:60], time.time()))
    return cur.lastrowid


def find(order_no: int):
    row = _conn.execute(
        "SELECT user_id, access_hash, owner_id, name, created, contacted FROM order_contacts WHERE order_no=?",
        (order_no,)).fetchone()
    if not row or time.time() - row[4] > ttl_sec():
        return None
    return dict(zip(("user_id", "access_hash", "owner_id", "name", "created", "contacted"), row))


# ---------- 3. Yuborish (istisnolar + anti-ban) ----------
_send_lock = asyncio.Lock()                  # bir vaqtda faqat bitta shaxsiy xabar
_sent_times: list[float] = []


async def _resolve(client: TelegramClient, user_id: int, access_hash: int | None):
    if access_hash is not None:
        return InputPeerUser(user_id, access_hash)
    return await client.get_input_entity(user_id)        # sessiya keshida bo'lsa ishlaydi


def driver_mention(driver) -> str:
    """Username bo'lsa @username. Bo'lmasa — ismga bosiladigan mention (tg://user).
    Telethon uni InputMessageEntityMentionName ga aylantiradi: haydovchi xabar ichiga «biriktiriladi»,
    shuning uchun mijoz username'siz ham ismga bosib profilni ochadi va yoza oladi."""
    if getattr(driver, "username", None):
        return f"@{driver.username}"
    name = html.escape(" ".join(x for x in (getattr(driver, "first_name", None),
                                            getattr(driver, "last_name", None)) if x) or "Haydovchi")
    return f'<a href="tg://user?id={driver.id}">{name}</a>'


async def send_dm(client: TelegramClient, user_id: int, access_hash: int | None, text: str) -> str:
    """Natija: ok | not_found | privacy | blocked | flood | limit | error"""
    try:
        peer = await _resolve(client, user_id, access_hash)
    except (ValueError, PeerIdInvalidError) as e:
        # Akkaunt bu odamni hech qachon "ko'rmagan": u guruhda qayta yozganda remember() yangilaydi
        log.warning("Mijoz topilmadi (user_id=%s): %s", user_id, e)
        return "not_found"

    async with _send_lock:
        now = time.time()
        _sent_times[:] = [t for t in _sent_times if now - t < 3600]
        if len(_sent_times) >= DM_PER_HOUR:
            log.warning("Soatlik shaxsiy xabar limiti (%s) to'ldi", DM_PER_HOUR)
            return "limit"
        await asyncio.sleep(random.uniform(*DM_DELAY))
        for attempt in (1, 2):
            try:
                await client.send_message(peer, text, parse_mode="html")
                _sent_times.append(time.time())
                return "ok"
            except FloodWaitError as e:
                log.warning("FloodWait: %s s kutamiz", e.seconds)
                if attempt == 2 or e.seconds > 900:          # juda uzoq bo'lsa voz kechamiz
                    return "flood"
                await asyncio.sleep(e.seconds + 1)
            except PeerFloodError:
                log.error("PeerFlood: akkaunt notanishlarga yozishdan vaqtincha cheklangan")
                return "flood"
            except UserPrivacyRestrictedError:
                return "privacy"
            except (UserIsBlockedError, InputUserDeactivatedError):
                return "blocked"
            except (ValueError, PeerIdInvalidError) as e:    # hash eskirgan
                log.warning("Peer yaroqsiz (user_id=%s): %s", user_id, e)
                return "not_found"
            except Exception as e:
                log.error("Shaxsiy xabar yuborilmadi: %s", e)
                return "error"
    return "error"


# ---------- 2. Haydovchi javobi -> mijozga xabar ----------
_REPLY = {
    "ok": "✅ Mijozga xabar yuborildi. U sizga yozadi.",
    "not_found": "⚠️ Mijozga yozib bo'lmadi (akkaunt uni topa olmadi). Telefon raqami orqali bog'laning.",
    "privacy": "⚠️ Mijoz notanishlardan xabar olishni yopib qo'ygan.",
    "blocked": "⚠️ Mijoz akkauntni bloklagan yoki o'chirilgan.",
    "flood": "⏳ Telegram cheklovi. Birozdan keyin qayta urinib ko'ring.",
    "limit": "⏳ Soatlik limit to'ldi. Birozdan keyin qayta urinib ko'ring.",
    "error": "❌ Xatolik. Telefon raqami orqali bog'laning.",
}


async def _order_no_from(event) -> int | None:
    m = ORDER_RE.search(event.raw_text or "")
    if not m and event.is_reply:
        replied = await event.get_reply_message()
        m = ORDER_RE.search(getattr(replied, "raw_text", "") or "")
    return int(m.group(1)) if m else None


_REPLY.update({
    "expired": "⌛ Bu buyurtma eskirgan. Telefon raqami orqali bog'laning.",
    "already": "ℹ️ Bu mijozga allaqachon boshqa haydovchi orqali xabar yuborilgan.",
    "other_account": "⚠️ Bu mijozni boshqa userbot akkaunti ko'rgan, yozib bo'lmadi.",
    "no_userbot": "⚠️ Userbot hozir ishlamayapti. Telefon raqami orqali bog'laning.",
})


async def contact(client: TelegramClient, order_no: int, driver_id: int, driver_username: str | None,
                  driver_name: str | None) -> str:
    """«💬 Yozish» tugmasi (username'siz mijoz): mijozga «haydovchi bog'lanmoqchi» deb yozadi. Natija kaliti _REPLY da."""
    rec = find(order_no)
    if not rec:
        return "expired"
    if rec["owner_id"] != (await client.get_me()).id:
        return "other_account"
    if rec["contacted"]:
        return "already"
    if driver_username:
        mention = f"@{driver_username}"
    else:
        try:                                # mention ishlashi uchun userbot haydovchini tanishi kerak
            await client.get_input_entity(driver_id)
            mention = f'<a href="tg://user?id={driver_id}">{html.escape(driver_name or "Haydovchi")}</a>'
        except (ValueError, PeerIdInvalidError):
            mention = html.escape(driver_name or "Haydovchi")
    _conn.execute("UPDATE order_contacts SET contacted=1 WHERE order_no=?", (order_no,))   # ikki haydovchi bossa ham bir marta
    res = await send_dm(client, rec["user_id"], rec["access_hash"], DM_TEXT.format(driver=mention))
    if res != "ok":
        _conn.execute("UPDATE order_contacts SET contacted=0 WHERE order_no=?", (order_no,))
    return res


def register(client: TelegramClient, closed_chat_ids):
    """Yopiq guruhlarda haydovchi #Order_N e'longa reply qilsa — mijozga yozadi.
    closed_chat_ids: chaqiriladigan funksiya (ro'yxat ish davomida o'zgaradi)."""
    owner = {"id": None}

    @client.on(events.NewMessage(incoming=True))
    async def on_driver_reply(event):
        if event.chat_id not in closed_chat_ids():
            return
        order_no = await _order_no_from(event)
        if not order_no:
            return
        if owner["id"] is None:
            owner["id"] = (await client.get_me()).id
        rec = find(order_no)
        if not rec:
            await event.reply(f"⌛ #Order_{order_no} eskirgan yoki topilmadi.")
            return
        if rec["owner_id"] != owner["id"]:          # access_hash boshqa akkauntniki
            return
        if rec["contacted"]:
            await event.reply("ℹ️ Bu mijozga allaqachon xabar yuborilgan.")
            return
        driver = await event.get_sender()
        res = await send_dm(client, rec["user_id"], rec["access_hash"], DM_TEXT.format(driver=driver_mention(driver)))
        if res == "ok":
            _conn.execute("UPDATE order_contacts SET contacted=1 WHERE order_no=?", (order_no,))
        await event.reply(_REPLY[res])

    client.loop.create_task(purge_loop())
