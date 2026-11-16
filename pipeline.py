"""Umumiy oqim: xabar -> tahlil -> (kerak bo'lsa AI) -> dedup -> navbat -> haydovchilar guruhi."""
import asyncio
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import ai
import config
import routes
from nlp import analyze, canon_city, normalize, worth_ai

log = logging.getLogger(__name__)
stats = {"seen": 0, "passenger": 0, "driver": 0, "unknown": 0, "ai_calls": 0, "ai_errors": 0,
         "dup": 0, "sent": 0, "failed": 0, "orders": 0, "relayed": 0}
MAX_ATTEMPTS = 4


@dataclass
class Incoming:
    text: str
    chat_id: int
    chat_title: str
    chat_username: str | None
    msg_id: int
    user_name: str | None
    username: str | None
    user_id: int | None


@dataclass
class Outgoing:
    text: str
    key: str
    attempts: int = 0
    passenger_id: int | None = None         # bot orqali buyurtma: "Oldim" bosilsa shu odamga xabar boradi
    done: asyncio.Future | None = None      # yuborish natijasi (True/False) kutayotgan uchun
    contact_url: str | None = None          # "Yozish" tugmasi


# ---------- Dedup ----------
_seen: dict[str, float] = {}


def _dup_key(phone, frm, to, seats, when, text, user_id):
    who = phone or (str(user_id) if user_id else "")
    # Marshrut to'liq bo'lsa so'zlar boshqacha bo'lsa ham dublikat; bo'lmasa matnning o'zi solishtiriladi
    what = f"{frm}|{to}|{seats}|{when}" if frm and to else normalize(text)[:120]
    return hashlib.md5(f"{who}|{what}".encode()).hexdigest()


def is_duplicate(key: str) -> bool:
    now, ttl = time.time(), config.DEDUP_MINUTES * 60
    for k in [k for k, t in _seen.items() if now - t > ttl]:
        del _seen[k]
    if key in _seen:
        return True
    _seen[key] = now
    return False


# ---------- Navbat (Telegram limitlari uchun) ----------
queue: asyncio.Queue = asyncio.Queue()


def contact_url(username, user_id):
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}" if user_id and user_id > 0 else None


def source_link(m: Incoming):
    if m.chat_username:
        return f"https://t.me/{m.chat_username}/{m.msg_id}"
    s = str(m.chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{m.msg_id}"
    return None


def route_hashtag(frm, to) -> str:
    """Yo'nalishdan Telegram hashtagi: "Toshkent","Termiz" -> "#Toshkent_Termiz". Filtrlab ko'rish uchun."""
    def tag(s):
        return re.sub(r"[^0-9A-Za-z]", "", (s or ""))     # faqat lotin harf/raqam; apostrof, probel, chiziqcha tushadi
    a, b = tag(frm), tag(to)
    if a and b:
        return f"#{a}_{b}"
    return f"#{a or b}" if (a or b) else ""


def render(m: Incoming, frm, to, seats, when, phone) -> str:
    e = html.escape
    route = f"{e(frm or '?')} → {e(to or '?')}"
    lines = ["🧍 <b>YO'LOVCHI</b>", f"📍 {route}"]
    if when:
        lines.append(f"🕕 {e(str(when))}")
    if seats:
        lines.append(f"👥 {seats} kishi")
    if phone:
        lines.append(f"📞 {e(phone)}")
    if m.username:
        lines.append(f"👤 @{e(m.username)}")
    elif m.user_id and m.user_id > 0:
        lines.append(f'👤 <a href="tg://user?id={m.user_id}">{e(m.user_name or "Profil")}</a>')
    lines.append(f"\n💬 <i>{e(m.text[:400])}</i>")
    link = source_link(m)
    src = f'<a href="{link}">{e(m.chat_title)}</a>' if link else e(m.chat_title)
    lines.append(f"🔗 {src}")
    tag = route_hashtag(frm, to)
    if tag:
        lines.append(tag)
    return "\n".join(lines)


def render_order(user_id, username, full_name, d: dict) -> str:
    e = html.escape
    lines = ["🚕 <b>YANGI BUYURTMA</b>", f"📍 {e(d['frm'])} → {e(d['to'])}", f"🕕 {e(d['when'])}"]
    if d.get("seats"):
        lines.append(f"👥 {d['seats']} kishi")
    lines.append(f"📞 {e(d['phone'])}")
    if username:
        lines.append(f"👤 @{e(username)}")
    else:
        lines.append(f'👤 <a href="tg://user?id={user_id}">{e(full_name or "Profil")}</a>')
    lines.append("🤖 Bot orqali buyurtma")
    return "\n".join(lines)


async def submit_order(user_id, username, full_name, d: dict, done: asyncio.Future):
    stats["orders"] += 1
    key = _dup_key(d["phone"], d["frm"], d["to"], d.get("seats"), d["when"], "", user_id)
    _seen[key] = time.time()                # guruhdagi xuddi shu e'lon haydovchilarga takror chiqmasin
    await queue.put(Outgoing(render_order(user_id, username, full_name, d), key,
                             passenger_id=user_id, done=done, contact_url=contact_url(username, user_id)))


async def process(m: Incoming) -> str | None:
    """Xabar turini qaytaradi: passenger, driver, unknown yoki other."""
    stats["seen"] += 1
    if not m.text or len(m.text) > config.MAX_LEN:
        return None
    p = analyze(m.text)
    label, frm, to, seats, when = p.label, p.frm, p.to, p.seats, p.when

    # Faqat noaniq va taksiga aloqasi bor xabarlar AI'ga boradi ("salom" kabilar limitni yemasin)
    if not p.confident and config.AI_API_KEY and worth_ai(m.text, p):
        stats["ai_calls"] += 1
        res = await ai.classify(m.text)
        if res:
            label = res["label"]
            frm = frm or canon_city(res["from"])
            to = to or canon_city(res["to"])
            seats = seats or res["seats"]
            when = when or res["time"]
        else:
            stats["ai_errors"] += 1

    stats[label if label in ("passenger", "driver") else "unknown"] += 1
    log.info("[%s] %s | %s→%s | %s", label, m.chat_title, frm, to, m.text[:60].replace("\n", " "))
    if label != "passenger":
        return label
    if not routes.allowed(frm, to):     # xizmat qilinmaydigan yo'nalish: maxfiy guruhga yuborilmaydi
        return label
    key = _dup_key(p.phone, frm, to, seats, when, m.text, m.user_id)
    if is_duplicate(key):
        stats["dup"] += 1
        return label
    await queue.put(Outgoing(render(m, frm, to, seats, when, p.phone), key,
                             contact_url=contact_url(m.username, m.user_id)))
    return label


def taken_kb(passenger_id=None, url=None):
    data = f"take:{passenger_id}" if passenger_id else "take"
    row = [InlineKeyboardButton(text="✅ Oldim", callback_data=data)]
    if url:
        row.append(InlineKeyboardButton(text="💬 Yozish", url=url))
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def _deliver(bot: Bot, item: Outgoing):
    async def send(url):
        await bot.send_message(config.DRIVERS_CHAT_ID, item.text, parse_mode="HTML",
                               reply_markup=taken_kb(item.passenger_id, url), disable_web_page_preview=True)

    try:
        await send(item.contact_url)
    except TelegramBadRequest as e:
        # Yo'lovchi maxfiylik sozlamasi tg://user tugmasini taqiqlasa, Telegram butun xabarni rad etadi
        if not (item.contact_url and "BUTTON_USER" in str(e)):
            raise
        log.info("Yozish tugmasi olib tashlandi: yo'lovchi maxfiyligi cheklangan")
        await send(None)


def _finish(item: Outgoing, ok: bool):
    if item.done and not item.done.done():
        item.done.set_result(ok)


async def sender(bot: Bot):
    while True:
        item = await queue.get()
        try:
            await _deliver(bot, item)
            stats["sent"] += 1
            _finish(item, True)
        except TelegramRetryAfter as e:      # limit: kutib, qayta yuboramiz
            log.warning("Telegram limiti, %s s kutamiz", e.retry_after)
            await asyncio.sleep(e.retry_after)
            await queue.put(item)
        except (TelegramNetworkError, TelegramServerError) as e:  # vaqtinchalik xato
            item.attempts += 1
            if item.attempts < MAX_ATTEMPTS:
                log.warning("Yuborilmadi (%s-urinish): %s", item.attempts, e)
                await asyncio.sleep(2 ** item.attempts)
                await queue.put(item)
            else:
                _give_up(item, e)
        except Exception as e:
            _give_up(item, e)
        await asyncio.sleep(config.SEND_INTERVAL_SEC)


def _give_up(item: Outgoing, error):
    stats["failed"] += 1
    _seen.pop(item.key, None)                # yetkazilmagan e'lon qayta yozilsa, dublikat sanalmasin
    log.error("Yuborishda xato: %s", error)
    _finish(item, False)
