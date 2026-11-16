"""Guruh moderatsiyasi: kirdi-chiqdi xabarlari, reklama/havola, flood.

Bot qo'shilgan istalgan guruhda ishlaydi (kuzatuv ro'yxatidan qat'i nazar).
Har bir guruh adminlari /settings bilan funksiyalarni yoqib-o'chiradi.
Sozlamalar va hisoblagichlar moderation.json da saqlanadi.
"""
import asyncio
import html
import json
import logging
import os
import re
import time
from collections import defaultdict, deque

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config

log = logging.getLogger(__name__)
router = Router()
GROUPS = {"group", "supergroup"}

DEFAULTS = {"joins": True, "ads": True, "flood": True}
LABELS = {"joins": "Kirdi-chiqdi xabarlari", "ads": "Reklama va havolalar", "flood": "Flood (ketma-ket yozish)"}

FLOOD_COUNT, FLOOD_WINDOW = 5, 10       # 10 soniyada 5 tadan ko'p xabar
REPEAT_COUNT, REPEAT_WINDOW = 3, 120    # 2 daqiqada bir xil matn 3 marta
MUTE_SEC = 300
WARN_TTL = 20                           # ogohlantirish shuncha soniyadan keyin o'chadi
WARN_EVERY = 60                         # bir odamga ogohlantirish shundan tez-tez chiqmaydi
ADMINS_TTL = 600

_LINK = re.compile(
    r"https?://|www\.|\bt\.me/|\btelegram\.(?:me|dog)/"
    r"|(?<![@\w.])[a-z0-9-]{2,}\.(?:uz|ru|com|net|org|me|io|xyz|site|online|shop|top|info)\b",
    re.I,
)
_SPAM = re.compile(
    r"obuna\s*bo.?ling|kanal(?:imiz)?ga\s*(?:qo.?shiling|kiring|a.?zo)|ishonchli\s*daromad"
    r"|подпиш|подписыва|заработ|казино|casino|1xbet|melbet|ставк",
    re.I,
)

WELCOME = (
    "👋 Salom! Men guruhni tozalab turaman:\n"
    "• kirdi-chiqdi xabarlarini o'chiraman\n"
    "• reklama va begona havolalarni o'chiraman\n"
    f"• flood qilganlarni {MUTE_SEC // 60} daqiqaga cheklayman\n\n"
    "Ishlashim uchun meni <b>admin</b> qiling (xabar o'chirish va foydalanuvchini cheklash huquqi bilan).\n"
    "Sozlash: /settings (faqat guruh adminlari).\n\n"
    "ℹ️ Guruhdagi taksi yo'lovchi e'lonlari hamkor haydovchilar guruhiga ham yetkazilishi mumkin."
)


# ---------- Saqlash ----------
_data: dict | None = None   # {"chat_id": {"on": {...}, "counts": {...}}}


def _load() -> dict:
    global _data
    if _data is None:
        try:
            _data = json.loads(config.MOD_FILE.read_text(encoding="utf-8")) if config.MOD_FILE.exists() else {}
        except (OSError, ValueError) as e:
            log.error("%s o'qilmadi (%s), standart sozlamalar ishlatiladi", config.MOD_FILE.name, e)
            _data = {}
    return _data


def _save():
    tmp = config.MOD_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, config.MOD_FILE)


def _entry(chat_id) -> dict:
    return _load().setdefault(str(chat_id), {"on": {}, "counts": {}})


def settings(chat_id) -> dict:
    return {**DEFAULTS, **_load().get(str(chat_id), {}).get("on", {})}


def toggle(chat_id, key) -> bool:
    new = not settings(chat_id)[key]
    _entry(chat_id)["on"][key] = new
    _save()
    return new


def counts(chat_id) -> dict:
    return {k: _load().get(str(chat_id), {}).get("counts", {}).get(k, 0) for k in DEFAULTS}


def bump(chat_id, key):
    c = _entry(chat_id)["counts"]
    c[key] = c.get(key, 0) + 1
    _save()


def migrate(old_id, new_id):
    d = _load()
    if str(old_id) in d:
        d[str(new_id)] = d.pop(str(old_id))
        _save()


# ---------- Aniqlash (sof funksiyalar, testlanadi) ----------
def ad_reason(msg: Message, bot_username: str | None = None) -> str | None:
    """Xabar reklama bo'lsa sababini qaytaradi."""
    if msg.sender_chat and msg.sender_chat.id != msg.chat.id and not msg.is_automatic_forward:
        return "kanal nomidan yozilgan"
    origin = msg.forward_origin
    if origin and origin.type in ("channel", "chat"):
        return "kanaldan forward"
    if msg.via_bot:
        return "inline bot"
    if msg.reply_markup and any(b.url for row in msg.reply_markup.inline_keyboard for b in row):
        return "havolali tugma"
    text = msg.text or msg.caption or ""
    own = {x.lower() for x in (msg.from_user.username if msg.from_user else None, bot_username) if x}
    for e in msg.entities or msg.caption_entities or []:
        if e.type in ("url", "text_link"):
            return "havola"
        if e.type == "mention" and e.extract_from(text)[1:].lower() not in own:
            return "begona @username"
    if _LINK.search(text):
        return "havola"
    if _SPAM.search(text):
        return "reklama matni"
    return None


_recent: dict[tuple[int, int], deque] = defaultdict(deque)   # (chat, user) -> [(vaqt, matn)]


def flood_hit(chat_id: int, user_id: int, text: str | None, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    q = _recent[(chat_id, user_id)]
    q.append((now, text))
    while q and now - q[0][0] > max(FLOOD_WINDOW, REPEAT_WINDOW):
        q.popleft()
    if len(_recent) > 20000:                # eski yozuvlarni tozalash
        for k in [k for k, v in _recent.items() if not v or now - v[-1][0] > REPEAT_WINDOW]:
            del _recent[k]
    burst = sum(1 for t, _ in q if now - t <= FLOOD_WINDOW)
    same = sum(1 for t, x in q if x == text and now - t <= REPEAT_WINDOW) if text else 0
    return burst > FLOOD_COUNT or same >= REPEAT_COUNT


# ---------- Telegram bilan ishlash ----------
_admins: dict[int, tuple[float, set[int]]] = {}
_no_rights_logged: dict[int, float] = {}
_muted: dict[tuple[int, int], float] = {}
_warned: dict[tuple[int, int], float] = {}
_tasks: set[asyncio.Task] = set()


async def _group_admins(bot: Bot, chat_id: int) -> set[int] | None:
    hit = _admins.get(chat_id)
    if hit and time.monotonic() - hit[0] < ADMINS_TTL:
        return hit[1]
    try:
        ids = {m.user.id for m in await bot.get_chat_administrators(chat_id)}
    except TelegramAPIError as e:
        log.warning("Guruh adminlarini olib bo'lmadi %s: %s", chat_id, e)
        return None
    _admins[chat_id] = (time.monotonic(), ids)
    return ids


async def _privileged(msg: Message, bot: Bot) -> bool:
    """Guruh admini, guruhning o'zi yoki bog'langan kanal. Tekshirib bo'lmasa ham tegmaymiz."""
    if msg.sender_chat:
        return msg.sender_chat.id == msg.chat.id or bool(msg.is_automatic_forward)
    u = msg.from_user
    if not u or u.is_bot or u.id in config.ADMIN_IDS:
        return True
    admins = await _group_admins(bot, msg.chat.id)
    return admins is None or u.id in admins


async def _can_manage(bot: Bot, chat_id: int, user_id: int, sender_chat=None) -> bool:
    if sender_chat is not None:
        return sender_chat.id == chat_id      # anonim admin
    if user_id in config.ADMIN_IDS:
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    return m.status in ("creator", "administrator")


async def _delete(bot: Bot, msg: Message) -> bool:
    try:
        await bot.delete_message(msg.chat.id, msg.message_id)
        return True
    except TelegramAPIError as e:
        last = _no_rights_logged.get(msg.chat.id, 0)
        if time.monotonic() - last > 3600:
            _no_rights_logged[msg.chat.id] = time.monotonic()
            log.warning("Xabarni o'chirib bo'lmadi (%s): %s. Botni admin qiling.", msg.chat.title, e)
        return False


async def _mute(bot: Bot, chat_id: int, user_id: int):
    key = (chat_id, user_id)
    if _muted.get(key, 0) > time.monotonic():
        return
    _muted[key] = time.monotonic() + MUTE_SEC
    try:
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False),
                                       until_date=int(time.time()) + MUTE_SEC)
    except TelegramAPIError as e:
        log.warning("Cheklab bo'lmadi %s/%s: %s", chat_id, user_id, e)


async def _delete_later(bot: Bot, chat_id: int, message_id: int):
    await asyncio.sleep(WARN_TTL)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass


async def _warn(bot: Bot, msg: Message, kind: str):
    u = msg.from_user
    if not u or u.is_bot:
        return
    key = (msg.chat.id, u.id)
    if time.monotonic() - _warned.get(key, -WARN_EVERY) < WARN_EVERY:
        return
    _warned[key] = time.monotonic()
    if len(_warned) > 20000:
        _warned.clear()
    who = f'<a href="tg://user?id={u.id}">{html.escape(u.full_name)}</a>'
    text = (f"⚠️ {who}, ketma-ket ko'p yozmang. {MUTE_SEC // 60} daqiqa yoza olmaysiz." if kind == "flood"
            else f"⚠️ {who}, guruhda reklama va havola tashlash mumkin emas.")
    try:
        sent = await bot.send_message(msg.chat.id, text, parse_mode="HTML")
    except TelegramAPIError:
        return
    t = asyncio.create_task(_delete_later(bot, msg.chat.id, sent.message_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _violation(count_flood: bool):
    async def check(msg: Message, bot: Bot):
        if msg.chat.id == config.DRIVERS_CHAT_ID:
            return False
        s = settings(msg.chat.id)
        kind = reason = None
        if s["ads"]:
            reason = ad_reason(msg, (await bot.me()).username)
            kind = "ads" if reason else None
        if not kind and count_flood and s["flood"] and msg.from_user:
            if flood_hit(msg.chat.id, msg.from_user.id, msg.text or msg.caption):
                kind, reason = "flood", "flood"
        if not kind or await _privileged(msg, bot):
            return False
        return {"kind": kind, "reason": reason}
    return check


# ---------- Handlerlar ----------
@router.message(F.chat.type.in_(GROUPS), F.new_chat_members | F.left_chat_member)
async def on_service(msg: Message, bot: Bot):
    if msg.chat.id != config.DRIVERS_CHAT_ID and settings(msg.chat.id)["joins"] and await _delete(bot, msg):
        bump(msg.chat.id, "joins")


@router.message(F.chat.type.in_(GROUPS), _violation(count_flood=True))
@router.edited_message(F.chat.type.in_(GROUPS), _violation(count_flood=False))
async def on_violation(msg: Message, bot: Bot, kind: str, reason: str):
    if not await _delete(bot, msg):
        return
    bump(msg.chat.id, kind)
    u = msg.from_user
    log.info("O'chirildi [%s] %s: %s", reason, msg.chat.title, u.id if u else msg.sender_chat.id)
    if kind == "flood" and u:
        await _mute(bot, msg.chat.id, u.id)
    await _warn(bot, msg, kind)


async def _view(bot: Bot, chat_id: int, title: str):
    s, c = settings(chat_id), counts(chat_id)
    lines = [f"⚙️ <b>{html.escape(title)}</b>: sozlamalar", ""]
    lines += [f"{'✅' if s[k] else '❌'} {label}" for k, label in LABELS.items()]
    lines += ["", f"🧹 O'chirilgan: reklama {c['ads']}, kirdi-chiqdi {c['joins']}, flood {c['flood']}"]
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        ok = me.status == "creator" or (me.status == "administrator" and getattr(me, "can_delete_messages", False)
                                         and getattr(me, "can_restrict_members", False))
    except TelegramAPIError:
        ok = False
    if not ok:
        lines += ["", "⚠️ Ishlashim uchun meni admin qiling: «Xabarlarni o'chirish» va "
                      "«Foydalanuvchilarni bloklash» huquqlari bilan."]
    kb = [[InlineKeyboardButton(text=f"{'✅' if s[k] else '❌'} {label}", callback_data=f"mod:{k}")]
          for k, label in LABELS.items()]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(Command("settings"), F.chat.type.in_(GROUPS))
async def on_settings(msg: Message, bot: Bot):
    if not await _can_manage(bot, msg.chat.id, msg.from_user.id if msg.from_user else 0, msg.sender_chat):
        return
    text, kb = await _view(bot, msg.chat.id, msg.chat.title or "")
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("mod:"))
async def on_toggle(cb: CallbackQuery, bot: Bot):
    key = cb.data[4:]
    if key not in DEFAULTS or not isinstance(cb.message, Message):
        await cb.answer()
        return
    chat = cb.message.chat
    if not await _can_manage(bot, chat.id, cb.from_user.id):
        await cb.answer("Faqat guruh adminlari o'zgartira oladi", show_alert=True)
        return
    on = toggle(chat.id, key)
    text, kb = await _view(bot, chat.id, chat.title or "")
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramAPIError:
        pass
    await cb.answer(f"{LABELS[key]}: {'yoqildi' if on else 'o‘chirildi'}")


async def welcome(bot: Bot, chat_id: int):
    try:
        await bot.send_message(chat_id, WELCOME, parse_mode="HTML")
    except TelegramAPIError as e:
        log.info("Guruhga salom yozib bo'lmadi %s: %s", chat_id, e)
