"""Umumiy oqim: xabar -> tahlil -> (kerak bo'lsa AI) -> dedup -> navbat -> haydovchilar guruhi."""
import asyncio
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat,
                                TelegramNetworkError, TelegramRetryAfter, TelegramServerError)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import ai
import config
import routes
from nlp import analyze, canon_city, is_spam, normalize, tel, tidy, worth_ai
from services import learn

log = logging.getLogger(__name__)
stats = {"seen": 0, "passenger": 0, "driver": 0, "unknown": 0, "ai_calls": 0, "ai_errors": 0,
         "ai_overrides": 0, "learn_hits": 0, "spam": 0, "donor": 0, "donor_skipped": 0, "dup": 0, "sent": 0,
         "failed": 0, "orders": 0, "relayed": 0}
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
    phone: str | None = None            # muallif profilidagi ochiq raqam (userbot ko'rsa); matnda bo'lmasa ishlatiladi
    access_hash: int | None = None      # userbot ko'rgan muallif (username'siz mijozga #Order orqali yozish uchun)
    owner_id: int | None = None         # mijozni ko'rgan userbot akkaunti


@dataclass
class Outgoing:
    text: str
    key: str
    attempts: int = 0
    passenger_id: int | None = None         # bot orqali buyurtma: "Oldim" bosilsa shu odamga xabar boradi
    done: asyncio.Future | None = None      # yuborish natijasi (True/False) kutayotgan uchun
    contact_url: str | None = None          # "Yozish" tugmasi
    chat_id: int | None = None              # yopiq guruh (Smart Routing). None = DRIVERS_CHAT_ID
    style: str = "default"                  # "donor": «👤 Клиент личкаси» + «✅ Buyurtmani oldim» tugmalari
    undo_keys: list | None = None           # donor dublikat kalitlari: yetkazilmasa bazadan olib tashlanadi
    source_url: str | None = None           # «🔗 Xabarga o'tish»: asl xabar (lichka yopiq bo'lsa ismiga bosib yoziladi)
    order_no: int | None = None             # username'siz mijoz: «💬 Yozish» tugmasi userbot orqali yozadi
    route: tuple | None = None              # (frm, to): yuborish oldidan yopiq guruh qayta aniqlanadi (admin almashtirsa)
    mention: dict | None = None             # username'siz o'z xabari: userbot e'longa mention reply qiladi


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


# Boshqa botlar qayta joylagan e'lonlardagi xizmat qatorlari: haydovchiga foydasiz
_JUNK_LINE_RE = re.compile(
    r"(user\s*id|клиент\s*личка|клиентга\s*ёз|mijoz\s*lichka|mijozga\s*yoz|t\.me/|@\w+bot\b|orqali yuborildi)",
    re.I)
_REPOST_ID_RE = re.compile(r"user\s*id\s*[:：]?\s*(\d{5,15})", re.I)


def clean_text(text: str) -> str:
    keep = [ln for ln in text.splitlines() if not _JUNK_LINE_RE.search(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip() or text.strip()


def repost_user_id(text: str) -> int | None:
    """Qayta joylangan e'londa asl mijozning ID si ("🆔 User ID: 8898901836")."""
    m = _REPOST_ID_RE.search(text or "")
    return int(m.group(1)) if m else None


def _repost_name(text: str) -> str | None:
    """"👤 Akmal Choriyev" qatoridan ism (faqat ID qatoridan oldingi)."""
    for ln in text.splitlines():
        if _REPOST_ID_RE.search(ln):
            break
        mm = re.match(r"\s*👤\s*(.+)", ln)
        if mm:
            return mm.group(1).strip()[:40]
    return None


def render(m: Incoming, frm, to, seats, when, phone, order_no: int | None = None,
           text_phone=None, profile_phone=None, username: str | None = None) -> str:
    """Yagona format (services/card.py) — donor e'lonlari bilan bir xil."""
    from services.card import render_card
    if text_phone is None and profile_phone is None:
        text_phone = phone
    rid = repost_user_id(m.text)
    name = (_repost_name(m.text) if rid else None) or m.user_name
    return render_card(frm=frm, to=to, when=when, seats=seats, text_phone=text_phone, profile_phone=profile_phone,
                       name=name, username=username or (None if rid else m.username),
                       text=tidy(m.text) or clean_text(m.text)[:400], source_title=m.chat_title,
                       source_url=source_link(m), order_no=order_no,
                       user_id=rid or (m.user_id if m.user_id and m.user_id > 0 else None))


def render_order(user_id, username, full_name, d: dict) -> str:
    e = html.escape
    lines = ["🚕 <b>YANGI BUYURTMA</b>", f"📍 {e(d['frm'])} → {e(d['to'])}", f"🕕 {e(d['when'])}"]
    if d.get("seats"):
        lines.append(f"👥 {d['seats']} kishi")
    lines.append(f"📞 {e(tel(d['phone']))}")
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
                             passenger_id=user_id, done=done, contact_url=contact_url(username, user_id),
                             chat_id=routes.target_chat(canon_city(d["frm"]), canon_city(d["to"])),
                             route=(canon_city(d["frm"]), canon_city(d["to"]))))


def needs_ai(raw: str, p) -> bool:
    """AI'ga yuborish kerakmi: kalit so'zlar noaniq bo'lsa, yoki "yo'lovchi" chiqqan-u, matnda haydovchi
    belgilari ham bo'lsa (noto'g'ri e'lon maxfiy guruhga tushmasligi uchun). "Salom" kabilar limitni yemaydi."""
    if not (config.AI_API_KEY and worth_ai(raw, p)):
        return False
    return not p.confident or (p.label == "passenger" and p.scores.get("driver", 0) > 0)


async def decide(raw: str, p) -> tuple[str, str, dict | None]:
    """Xabar egasi kim: (label, manba, AI javobi). manba: "kw", "learn" (o'rganilgan belgilar) yoki "ai"."""
    if not needs_ai(raw, p):
        return p.label, "kw", None
    # AI'ga yubormasdan oldin: o'rganilgan haydovchi belgilari yetarli bo'lsa (va yo'lovchiga og'magan bo'lsa)
    if p.scores.get("driver", 0) >= p.scores.get("passenger", 0) and learn.guess(raw) == "driver":
        stats["learn_hits"] += 1
        return "driver", "learn", None
    stats["ai_calls"] += 1
    res = await ai.classify(raw)
    if not res:
        stats["ai_errors"] += 1
        return p.label, "kw", None              # AI ishlamasa: kalit so'z natijasi (noaniq bo'lsa tashlanadi)
    sure = res["confidence"] >= config.AI_MIN_CONFIDENCE
    if p.confident:                             # tekshiruv: AI ishonch bilan boshqacha desa, AI ustun
        if sure and res["label"] != p.label:
            stats["ai_overrides"] += 1
            log.info("AI tuzatdi: %s -> %s (%.2f) | %s", p.label, res["label"], res["confidence"],
                     raw[:60].replace("\n", " "))
            return res["label"], "ai", res
        return p.label, "ai", res
    if res["label"] == "passenger" and p.scores.get("driver", 0) > p.scores.get("passenger", 0):
        # matnda haydovchi belgilari ko'proq: maxfiy guruhga faqat AI juda ishonchli bo'lsa o'tadi
        sure = res["confidence"] >= max(config.AI_MIN_CONFIDENCE, 0.85)
    return (res["label"] if sure else "unknown"), "ai", res


async def process(m: Incoming) -> str | None:
    """Xabar turini qaytaradi: passenger, driver, unknown yoki other."""
    stats["seen"] += 1
    if not m.text or len(m.text) > config.MAX_LEN:
        return None
    if is_spam(m.text):                 # reklama / bot taklifi / "feyk xabar" — e'lon qilinmaydi
        stats["spam"] += 1
        log.info("[spam] %s | %s", m.chat_title, m.text[:60].replace("\n", " "))
        return "other"
    p = analyze(m.text)
    label, frm, to, seats, when = p.label, p.frm, p.to, p.seats, p.when

    label, src, res = await decide(m.text, p)
    if res:
        frm = frm or canon_city(res.get("from"))
        to = to or canon_city(res.get("to"))
        seats = seats or res.get("seats")
        when = when or res.get("time")
    # Ishonchli natijadan belgilarni o'rganamiz (keyingi o'xshash xabar AI'siz aniqlansin).
    # O'z-o'zini kuchaytirmaslik uchun "learn" manbasidan o'rganilmaydi.
    if label in ("passenger", "driver"):
        if src == "kw" and p.confident:
            learn.learn(m.text, label)
        elif src == "ai" and res and res["label"] == label \
                and res["confidence"] >= max(config.AI_MIN_CONFIDENCE, 0.8):
            learn.learn(m.text, label)

    stats[label if label in ("passenger", "driver") else "unknown"] += 1
    log.info("[%s/%s] %s | %s→%s | %s", label, src, m.chat_title, frm, to, m.text[:60].replace("\n", " "))
    if label != "passenger":
        return label
    if not routes.allowed(frm, to):     # xizmat qilinmaydigan yo'nalish: maxfiy guruhga yuborilmaydi
        return label
    if m.chat_id in routes.closed_chat_ids():   # yopiq guruhning o'zidan kelgan xabar qaytib tushmasin
        return label
    phone = p.phone or m.phone          # matnda raqam bo'lmasa, muallif profilidagi ochiq raqam
    key = _dup_key(phone, frm, to, seats, when, m.text, m.user_id)
    if is_duplicate(key):
        stats["dup"] += 1
        return label
    rid = repost_user_id(m.text)                # bot qayta joylagan bo'lsa — mijoz matndagi User ID
    username = None if rid else m.username
    client_id = rid or (m.user_id if (m.user_id and m.user_id > 0) else None)
    if client_id and not username:              # darhol: mijoz profilidan username / raqam / ism
        try:
            from services import enrich
            info = await enrich.lookup(client_id, None if rid else m.owner_id, None if rid else m.access_hash)
        except Exception as e:
            info = {}
            log.info("Profil ma'lumoti olinmadi: %s", e)
        username = info.get("username")
        if info.get("phone") and not m.phone and not rid:
            m.phone = info["phone"]
        if info.get("name") and not m.user_name:
            m.user_name = info["name"]
        if rid and info.get("phone"):
            m.phone = info["phone"]
        phone = p.phone or m.phone
    url = f"https://t.me/{username}" if username else None      # tg://user tugmalari ishlatilmaydi (rad etiladi)
    order_no = None
    if not username and (client_id or phone):   # username yo'q: «💬 Yozish» bosilsa bot mijozni qidiradi
        try:
            from services import order_contact
            order_no = order_contact.save(
                client_id, None if rid else m.access_hash, None if rid else (m.owner_id or order_contact.active_owner()),
                m.user_name, src_chat=m.chat_id, src_username=m.chat_username, src_msg=m.msg_id,
                snippet=(tidy(m.text) or m.text)[:200], phone=p.phone, profile_phone=m.phone)
        except Exception as e:                  # #Order ishlamasa ham e'lon yo'qolmasin
            log.warning("#Order saqlanmadi: %s", e)
    await queue.put(Outgoing(render(m, frm, to, seats, when, phone, order_no, text_phone=p.phone,
                                    profile_phone=m.phone, username=username), key,
                             contact_url=url, order_no=order_no,
                             chat_id=routes.target_chat(frm, to), source_url=source_link(m), route=(frm, to),
                             mention=None if (rid or username or not client_id) else {
                                 "user_id": client_id, "access_hash": m.access_hash, "owner_id": m.owner_id,
                                 "name": m.user_name, "src_chat": m.chat_id, "src_msg": m.msg_id}))
    return label


def taken_kb(passenger_id=None, url=None, style="default", source_url=None, order_no=None):
    """Hamma e'lon uchun bir xil, sodda tugmalar:  [✅ Oldim] [💬 Yozish]  /  [🔗 Xabarga o'tish]
    «💬 Yozish»: username bo'lsa t.me havolasi (lichka darhol ochiladi), bo'lmasa bot mijozni qidiradi (#Order)."""
    data = f"take:{passenger_id}" if passenger_id else "take"
    row = [InlineKeyboardButton(text="✅ Oldim", callback_data=data)]
    if url and (not url.startswith("tg://") or passenger_id):   # bot buyurtmasi: mijoz botni ochgan, tg:// ishlaydi
        row.append(InlineKeyboardButton(text="💬 Lichkaga yozish", url=url))      # o'zi to'g'ridan-to'g'ri yozadi
    elif order_no:
        row.append(InlineKeyboardButton(text="🤖 Bot orqali yozish", callback_data=f"oc:{order_no}"))
    rows = [row]
    if source_url:                                  # t.me havola tugmasi hech qachon rad etilmaydi
        rows.append([InlineKeyboardButton(text="🔗 Xabarga o'tish", url=source_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _deliver(bot: Bot, item: Outgoing):
    async def send(url):
        return await bot.send_message(item.chat_id or config.DRIVERS_CHAT_ID, item.text, parse_mode="HTML",
                               reply_markup=taken_kb(item.passenger_id, url, item.style, item.source_url, item.order_no),
                               disable_web_page_preview=True)

    try:
        return await send(item.contact_url)
    except TelegramMigrateToChat as e:
        # Yopiq guruh supergroup'ga aylantirilgan (masalan, kimnidir anonim admin qilganda) — ID o'zgaradi.
        # Bazadagi barcha havolalarni yangi ID ga o'tkazib, e'lonni qayta yuboramiz.
        old, new = item.chat_id or config.DRIVERS_CHAT_ID, e.migrate_to_chat_id
        from database import crud
        n = crud.migrate_chat(old, new)
        if config.DRIVERS_CHAT_ID == old:
            config.DRIVERS_CHAT_ID = new
            log.warning("DRIVERS_CHAT_ID o'zgardi: %s -> %s. .env dagi qiymatni ham yangilang!", old, new)
        log.warning("Guruh supergroup'ga aylantirilgan: %s -> %s (%s ta yozuv yangilandi)", old, new, n)
        item.chat_id = new
        return await _deliver(bot, item)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        # Yo'nalishning yopiq guruhiga yozib bo'lmasa (bot chiqarilgan, ID xato) — e'lon yo'qolmasin
        if item.chat_id and item.chat_id != config.DRIVERS_CHAT_ID and "BUTTON_USER" not in str(e):
            log.error("Yopiq guruhga yuborilmadi (chat=%s): %s. DRIVERS_CHAT_ID ga yuboriladi", item.chat_id, e)
            item.chat_id = None
            return await _deliver(bot, item)
        if not isinstance(e, TelegramBadRequest):
            raise
        # Yo'lovchi maxfiylik sozlamasi tg://user tugmasini taqiqlasa, Telegram butun xabarni rad etadi
        if not (item.contact_url and "BUTTON_USER" in str(e)):
            raise
        log.info("Yozish tugmasi olib tashlandi: yo'lovchi maxfiyligi cheklangan")
        return await send(None)


def _finish(item: Outgoing, ok: bool):
    if item.done and not item.done.done():
        item.done.set_result(ok)


# Telegram limiti: bitta guruhga ~20 xabar/daqiqa, umumiy ~30 xabar/soniya.
# Oldin bitta umumiy navbat har xabardan keyin SEND_INTERVAL_SEC kutardi va limit/xato kutishlari
# BARCHA guruhlarni to'xtatib qo'yardi. Endi har bir guruhning o'z navbati bor: guruhlar parallel ishlaydi.
_chat_queues: dict[int, asyncio.Queue] = {}
_global_gap = 1 / 25                         # umumiy limitdan pastda qolish uchun
_global_lock = asyncio.Lock()
_last_global = 0.0


async def _global_slot():
    global _last_global
    async with _global_lock:
        wait = _last_global + _global_gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_global = time.monotonic()


async def _chat_worker(bot: Bot, chat_q: asyncio.Queue):
    while True:
        item = await chat_q.get()
        if item.route is not None:          # navbatda turganda admin yopiq guruhni almashtirgan bo'lishi mumkin
            new = routes.target_chat(*item.route)
            if new != (item.chat_id or config.DRIVERS_CHAT_ID):
                log.info("Yopiq guruh o'zgargan: %s -> %s", item.chat_id, new)
                item.chat_id = new
                await _route(bot, item)
                continue
        try:
            await _global_slot()
            sent_msg = await _deliver(bot, item)
            stats["sent"] += 1
            if item.mention and sent_msg is not None:     # qo'shimcha: userbot mention reply (xatosi e'longa ta'sir qilmaydi)
                from services import mention_reply
                asyncio.create_task(mention_reply.send(sent_msg.chat.id, sent_msg.message_id, item.mention))
            # Yopiq guruhga uzatilgan har bir e'lon: grep "\[sent\]"
            info = " | ".join(x.strip() for x in item.text.splitlines()[1:3] if x.strip())
            log.info("[sent] → %s | %s | %s%s", item.chat_id or config.DRIVERS_CHAT_ID,
                     re.sub(r"<[^>]+>", "", info)[:80], "donor" if item.style == "donor" else "guruh",
                     f" | #Order_{item.order_no}" if item.order_no else "")
            _finish(item, True)
        except TelegramRetryAfter as e:      # limit faqat shu guruhni kuttiradi
            log.warning("Telegram limiti, %s s kutamiz", e.retry_after)
            await asyncio.sleep(e.retry_after)
            await chat_q.put(item)
            continue
        except (TelegramNetworkError, TelegramServerError) as e:  # vaqtinchalik xato
            item.attempts += 1
            if item.attempts < MAX_ATTEMPTS:
                log.warning("Yuborilmadi (%s-urinish): %s", item.attempts, e)
                await asyncio.sleep(2 ** item.attempts)
                await chat_q.put(item)
                continue
            _give_up(item, e)
        except Exception as e:
            _give_up(item, e)
        await asyncio.sleep(config.SEND_INTERVAL_SEC)   # guruh ichidagi oraliq


async def sender(bot: Bot):
    """Umumiy navbatdan olib, har bir guruhning o'z navbatiga tarqatadi."""
    while True:
        await _route(bot, await queue.get())


async def _route(bot: Bot, item: Outgoing):
    cid = item.chat_id or config.DRIVERS_CHAT_ID
    chat_q = _chat_queues.get(cid)
    if chat_q is None:
        chat_q = _chat_queues[cid] = asyncio.Queue()
        asyncio.create_task(_chat_worker(bot, chat_q))
    await chat_q.put(item)


def _give_up(item: Outgoing, error):
    stats["failed"] += 1
    _seen.pop(item.key, None)                # yetkazilmagan e'lon qayta yozilsa, dublikat sanalmasin
    if item.undo_keys:
        from database import crud
        crud.unmark_dispatched(item.undo_keys)
    log.error("Yuborishda xato: %s", error)
    _finish(item, False)
