"""Userbot agregator/tarqatkich.

Bitta userbot akkaunt (Telethon, main.run_userbot da ulanadi, admin.userbot) orqali:
  - tanlangan guruhlarga "yo'lovchi izlayman" e'lonini jadval bo'yicha tarqatadi,
  - o'sha guruhlar o'qiladi (main.run_userbot) va yo'lovchi e'lonlari maxfiy guruhga tushadi.

Boshqaruv: /agregator — reply-tugmalar (Guruhlar, E'lon matni, To'xtatish, Hisobot, Yordam, Akkauntni uzish).
Faqat admin. Sozlamalar aggregator.json da (store.py atomik-JSON naqshi).

Telethon chaqiruvlari admin.userbot orqali — test uchun admin.userbot ga soxta obyekt qo'yiladi.
"""
import asyncio
import html
import json
import logging
import os
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

import admin
import config

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
B = InlineKeyboardButton

# Reply-tugma matnlari
BTN_GROUPS = "👥 Guruhlar"
BTN_TEXT = "✍️ E'lon matni"
BTN_SEND = "📤 Hozir yuborish"
BTN_SCHED_ON = "▶️ Jadvalni yoqish"
BTN_SCHED_OFF = "⏸ Jadvalni to'xtatish"
BTN_REPORT = "📊 Hisobot"
BTN_HELP = "❓ Yordam"
BTN_LOGOUT = "❌ Akkauntni uzish"
BTN_ROLE = "⬅️ Rolni o'zgartirish"

logout_requested = False        # main.run_userbot buni ko'rib, ataylab uzilganda xato bermaydi
POLL_SEC = 30                   # broadcaster fon vazifasi shunча soniyada bir tekshiradi


class AdText(StatesGroup):
    waiting = State()


# ---------- Saqlash ----------
_data: dict | None = None
_DEFAULT = {"text": "", "interval_min": 0, "active": False, "groups": {},
            "last_round": 0.0, "day": "", "rounds_today": 0, "log": [], "notified_first": False}


def _load() -> dict:
    global _data
    if _data is None:
        try:
            raw = json.loads(config.AGG_FILE.read_text(encoding="utf-8")) if config.AGG_FILE.exists() else {}
        except (OSError, ValueError) as e:
            log.error("%s o'qilmadi (%s)", config.AGG_FILE.name, e)
            raw = {}
        _data = {**_DEFAULT, **raw}
        if not _data["interval_min"]:
            _data["interval_min"] = config.BROADCAST_MIN_INTERVAL_MIN
    return _data


def _save():
    tmp = config.AGG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_load(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, config.AGG_FILE)


def get_text() -> str:
    return _load()["text"]


def set_text(text: str):
    _load()["text"] = text.strip()
    _save()


def interval_min() -> int:
    return _load()["interval_min"]


def set_interval(minutes: int):
    _load()["interval_min"] = max(minutes, config.BROADCAST_MIN_INTERVAL_MIN)
    _save()


def is_active() -> bool:
    return _load()["active"]


def set_active(on: bool):
    _load()["active"] = on
    _save()


def set_groups(items: list[tuple[int, str]]):
    """Userbot akkaunt guruhlari ro'yxatini yangilaydi (on holatini saqlab qoladi)."""
    g = _load()["groups"]
    seen = set()
    for cid, title in items:
        k = str(cid)
        seen.add(k)
        g.setdefault(k, {"title": title, "on": False})
        g[k]["title"] = title
    for k in list(g):               # endi mavjud bo'lmagan guruhlarni olib tashlaymiz
        if k not in seen:
            del g[k]
    _save()


def groups() -> dict:
    return _load()["groups"]


def toggle_group(chat_id) -> bool:
    g = _load()["groups"].get(str(chat_id))
    if g is None:
        return False
    g["on"] = not g["on"]
    _save()
    return g["on"]


def active_group_ids() -> list[int]:
    return [int(k) for k, v in _load()["groups"].items() if v.get("on")]


def is_active_group(chat_id) -> bool:
    return _load()["groups"].get(str(chat_id), {}).get("on", False)


def _roll_day():
    today = time.strftime("%Y-%m-%d")
    d = _load()
    if d["day"] != today:
        d["day"], d["rounds_today"] = today, 0


def due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    d = _load()
    _roll_day()
    return bool(d["active"] and d["text"] and active_group_ids()
               and now - d["last_round"] >= d["interval_min"] * 60
               and d["rounds_today"] < config.BROADCAST_MAX_PER_DAY)


def start_round(now: float | None = None) -> bool:
    """Yangi siklni belgilaydi. Birinchi marta bo'lsa True (operatorга xabar berish uchun)."""
    now = time.time() if now is None else now
    _roll_day()
    d = _load()
    d["last_round"] = now
    d["rounds_today"] += 1
    first = not d["notified_first"]
    _save()
    return first


def record_post(chat_id, now: float | None = None):
    now = time.time() if now is None else now
    d = _load()
    d["log"].append([int(chat_id), now])
    cut = now - 86400
    d["log"] = [e for e in d["log"] if e[1] >= cut]     # 24 soatlik oyna
    _save()


def mark_notified():
    _load()["notified_first"] = True
    _save()


def report(now: float | None = None) -> list[tuple[str, int]]:
    """Oxirgi 24 soatda har guruhda nechta e'lon chiqqani (nom, soni), kamayish tartibida."""
    now = time.time() if now is None else now
    d = _load()
    cut = now - 86400
    counts: dict[str, int] = {}
    for cid, ts in d["log"]:
        if ts >= cut:
            title = d["groups"].get(str(cid), {}).get("title") or str(cid)
            counts[title] = counts.get(title, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


# ---------- Userbot adapteri (test uchun ajratilgan) ----------
async def _list_dialogs() -> list[tuple[int, str]]:
    ub = admin.userbot
    if ub is None:
        return []
    out = []
    async for d in ub.iter_dialogs():
        if getattr(d, "is_group", False):
            out.append((d.id, getattr(d, "title", "") or str(d.id)))
    return out


async def _send(chat_id: int, text: str):
    await admin.userbot.send_message(chat_id, text)


async def _broadcast(bot: Bot, text: str, targets: list[int], notify_first: bool = False) -> int:
    """Matnni barcha guruhlarga navbat bilan yuboradi. Yuborilган guruhlar sonini qaytaradi."""
    ok = 0
    for cid in targets:
        try:
            await _send(cid, text)
            record_post(cid)
            ok += 1
            if notify_first and ok == 1:
                await _notify_first(bot, cid)
        except Exception as e:              # FloodWait, chiqarib yuborilgan va h.k.
            log.warning("Tarqatib bo'lmadi guruh=%s: %s", cid, e)
        await asyncio.sleep(config.BROADCAST_GAP_SEC)
    return ok


# ---------- Fon vazifa: jadvalli tarqatish ----------
async def broadcaster(bot: Bot):
    """Doimo ishlaydi; sozlanmagan yoki vaqti kelmagan bo'lsa bekorга aylanadi."""
    while True:
        try:
            if admin.userbot is not None and due():
                first = start_round()
                targets = active_group_ids()
                ok = await _broadcast(bot, get_text(), targets, notify_first=first)
                log.info("Tarqatish sikli: %d/%d guruhga yuborildi", ok, len(targets))
        except Exception as e:
            log.error("Broadcaster xatosi: %s", e)
        await asyncio.sleep(POLL_SEC)


async def _notify_first(bot: Bot, chat_id: int):
    mark_notified()
    title = groups().get(str(chat_id), {}).get("title") or str(chat_id)
    for a in config.ADMIN_IDS:
        try:
            await bot.send_message(a, f"🎉 Birinchi e'loningiz chiqdi — «{title}» guruhida.\n"
                                      "Qolgan guruhlarga ham navbat bilan chiqadi. Natija: 📊 Hisobot")
        except TelegramAPIError:
            pass


# ---------- Menyu (aralash: asosiy pastdan reply, tanlash/tasdiqlash inline) ----------
HELP_TEXT = (
    "📣 <b>Qanday ishlaydi</b>\n\n"
    "Bitta userbot akkaunt bir nechta taksi guruhiga a'zo bo'ladi:\n"
    "• <b>Guruhlar</b> — akkaunt guruhlaridan ✅ qilasiz.\n"
    "• <b>E'lon matni</b> — \"yo'lovchi izlayman\" matnini yozasiz.\n"
    "• <b>Hozir yuborish</b> — tasdiqlab, darhol hamma tanlangan guruhga yuboradi.\n"
    "• <b>Jadvalni yoqish</b> — matnni belgilangan oraliqda avtomat takrorlab turadi.\n"
    "• Tanlangan guruhlar o'qiladi — yo'lovchi e'lonlari maxfiy guruhga yo'nalish hashtagi bilan tushadi.\n"
    "• <b>Hisobot</b> — oxirgi 24 soatda qaysi guruhda nechta e'lon chiqqani.\n\n"
    "⚠️ Juda tez-tez yuborish akkauntni bloklaydi."
)


def _menu_text() -> str:
    conn = "🟢 ulangan" if admin.userbot is not None else "🔴 ulanmagan (MODE=both + login)"
    sched = "🟢 yoqilgan" if is_active() else "🔴 o'chiq"
    return (f"📣 <b>Haydovchi — e'lon tarqatish</b>\n\n"
            f"Akkaunt: {conn}\nFaol guruhlar: {len(active_group_ids())}\n"
            f"E'lon matni: {'bor' if get_text() else 'yoʻq'}\n"
            f"Avtomat jadval: {sched} ({interval_min()} daq)\n\n"
            "Pastdagi tugmalardan foydalaning 👇")


def _menu_kb() -> ReplyKeyboardMarkup:
    sched = BTN_SCHED_OFF if is_active() else BTN_SCHED_ON
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_GROUPS), KeyboardButton(text=BTN_TEXT)],
        [KeyboardButton(text=BTN_SEND)],
        [KeyboardButton(text=sched), KeyboardButton(text=BTN_REPORT)],
        [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_LOGOUT)],
        [KeyboardButton(text=BTN_ROLE)],
    ], resize_keyboard=True)


def _role_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🧍 Yo'lovchiman", callback_data="role:passenger")],
        [B(text="🚕 Haydovchiman", callback_data="role:driver")]])


async def _is_admin(msg: Message, bot: Bot) -> bool:
    return bool(msg.from_user and await admin.is_admin(bot, msg.from_user.id))


async def _admin_cb(cb: CallbackQuery, bot: Bot) -> bool:
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer("Faqat adminlar uchun", show_alert=True)
        return False
    return True


async def show_menu(target: Message):
    """Agregator menyusini (pastdan chiqadigan tugmalar) ko'rsatadi. Rol tanlashdan ham chaqiriladi."""
    await target.answer(_menu_text(), parse_mode="HTML", reply_markup=_menu_kb())


@router.message(Command("agregator"))
async def on_open(msg: Message, bot: Bot):
    if await _is_admin(msg, bot):
        await show_menu(msg)


@router.message(F.text == BTN_HELP)
async def on_help(msg: Message, bot: Bot):
    if await _is_admin(msg, bot):
        await msg.answer(HELP_TEXT, parse_mode="HTML", reply_markup=_menu_kb())


@router.message(F.text == BTN_ROLE)
async def on_role(msg: Message, bot: Bot):
    if await _is_admin(msg, bot):
        await msg.answer("Siz kimsiz?", reply_markup=_role_kb())


# ---- E'lon matni (FSM) ----
@router.message(F.text == BTN_TEXT)
async def on_text_btn(msg: Message, bot: Bot, state: FSMContext):
    if not await _is_admin(msg, bot):
        return
    cur = get_text()
    await state.set_state(AdText.waiting)
    await msg.answer(("Joriy matn:\n\n" + cur + "\n\n" if cur else "")
                     + "Yangi e'lon matnini yuboring. Bekor: /cancel")


@router.message(StateFilter(AdText.waiting), Command("cancel"))
async def on_text_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await show_menu(msg)


@router.message(StateFilter(AdText.waiting))
async def on_text_set(msg: Message, state: FSMContext):
    if not (msg.text and msg.text.strip()):
        await msg.answer("Matn yuboring yoki /cancel")
        return
    set_text(msg.text.strip())
    await state.clear()
    await msg.answer("✅ E'lon matni saqlandi.", reply_markup=_menu_kb())


# ---- Jadval ----
@router.message(F.text.in_({BTN_SCHED_ON, BTN_SCHED_OFF}))
async def on_sched(msg: Message, bot: Bot):
    if not await _is_admin(msg, bot):
        return
    if not is_active():
        if not get_text():
            await msg.answer("❌ Avval ✍️ E'lon matni ni kiriting.", reply_markup=_menu_kb())
            return
        if not active_group_ids():
            await msg.answer("❌ Avval 👥 Guruhlardan tanlang.", reply_markup=_menu_kb())
            return
    set_active(not is_active())
    await msg.answer("▶️ Jadval yoqildi." if is_active() else "⏸ Jadval to'xtatildi.", reply_markup=_menu_kb())


# ---- Hisobot ----
@router.message(F.text == BTN_REPORT)
async def on_report(msg: Message, bot: Bot):
    if not await _is_admin(msg, bot):
        return
    rows = report()
    if not rows:
        await msg.answer("📊 Oxirgi 24 soatda e'lon chiqmadi.", reply_markup=_menu_kb())
        return
    total = sum(n for _, n in rows)
    lines = [f"📊 <b>Oxirgi 24 soat: {total} ta e'lon chiqdi</b>", ""] + [f"• {t}: {n}" for t, n in rows]
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=_menu_kb())


# ---- Guruhlarni tanlash (inline) ----
def _groups_text() -> str:
    return (f"👥 <b>Guruhlar</b> — tanlangan: {len(active_group_ids())}\n\n"
            "✅ belgili guruhlarga e'lon yuboriladi va ular o'qiladi. O'zgartirish uchun bosing.")


def _groups_kb() -> InlineKeyboardMarkup:
    rows = [[B(text=f"{'✅' if v.get('on') else '⬜'} {v.get('title', k)[:38]}", callback_data=f"agg:g:{k}")]
            for k, v in groups().items()]
    rows.append([B(text="✔️ Tayyor", callback_data="agg:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_GROUPS)
async def on_groups(msg: Message, bot: Bot):
    if not await _is_admin(msg, bot):
        return
    if admin.userbot is None:
        await msg.answer("🔴 Userbot ulanmagan. .env da MODE=both, API_ID/API_HASH, keyin terminalda login.",
                         reply_markup=_menu_kb())
        return
    try:
        dialogs = await _list_dialogs()
    except Exception as e:
        log.error("Dialoglarni olib bo'lmadi: %s", e)
        await msg.answer("❌ Guruhlar ro'yxatini olib bo'lmadi.", reply_markup=_menu_kb())
        return
    set_groups(dialogs)
    if not groups():
        await msg.answer("Akkaunt hali hеch qanday guruhga a'zo emas. Avval taksi guruhlarga qo'shiling.",
                         reply_markup=_menu_kb())
        return
    await msg.answer(_groups_text(), parse_mode="HTML", reply_markup=_groups_kb())


@router.callback_query(F.data.startswith("agg:g:"))
async def on_group_toggle(cb: CallbackQuery, bot: Bot):
    if not await _admin_cb(cb, bot):
        return
    toggle_group(cb.data[6:])
    try:
        await cb.message.edit_text(_groups_text(), parse_mode="HTML", reply_markup=_groups_kb())
    except TelegramAPIError:
        pass
    await cb.answer()


@router.callback_query(F.data == "agg:done")
async def on_groups_done(cb: CallbackQuery, bot: Bot):
    if not await _admin_cb(cb, bot):
        return
    try:
        await cb.message.edit_text(f"✅ Tanlangan guruhlar: {len(active_group_ids())}", parse_mode="HTML")
    except TelegramAPIError:
        pass
    await cb.answer("Saqlandi")


# ---- Hozir yuborish (reply tugma -> inline tasdiqlash) ----
@router.message(F.text == BTN_SEND)
async def on_send_btn(msg: Message, bot: Bot):
    if not await _is_admin(msg, bot):
        return
    text, n = get_text(), len(active_group_ids())
    if admin.userbot is None:
        await msg.answer("🔴 Userbot ulanmagan.", reply_markup=_menu_kb())
        return
    if not text:
        await msg.answer("❌ Avval ✍️ E'lon matni ni kiriting.", reply_markup=_menu_kb())
        return
    if not n:
        await msg.answer("❌ Avval 👥 Guruhlardan tanlang.", reply_markup=_menu_kb())
        return
    await msg.answer(f"📤 Shu xabar <b>{n}</b> ta guruhga yuborilsinmi?\n\n<i>{html.escape(text[:400])}</i>",
                     parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                         [B(text=f"✅ Ha, {n} guruhga yuborish", callback_data="agg:send_do")],
                         [B(text="❌ Bekor", callback_data="agg:cancel")]]))


@router.callback_query(F.data == "agg:cancel")
async def on_cancel_inline(cb: CallbackQuery, bot: Bot):
    if not await _admin_cb(cb, bot):
        return
    try:
        await cb.message.edit_text("Bekor qilindi.")
    except TelegramAPIError:
        pass
    await cb.answer()


@router.callback_query(F.data == "agg:send_do")
async def on_send_do(cb: CallbackQuery, bot: Bot):
    if not await _admin_cb(cb, bot):
        return
    text, targets = get_text(), active_group_ids()
    if admin.userbot is None or not text or not targets:
        try:
            await cb.message.edit_text("❌ Yuborib bo'lmadi (userbot/matn/guruh yo'q).")
        except TelegramAPIError:
            pass
        await cb.answer()
        return
    try:
        await cb.message.edit_text("📤 Yuborilmoqda...")
    except TelegramAPIError:
        pass
    await cb.answer()
    ok = await _broadcast(bot, text, targets)
    await cb.message.answer(f"✅ {ok}/{len(targets)} guruhga yuborildi.", reply_markup=_menu_kb())


# ---- Akkauntni uzish (reply tugma -> inline tasdiqlash) ----
@router.message(F.text == BTN_LOGOUT)
async def on_logout_btn(msg: Message, bot: Bot):
    if not await _is_admin(msg, bot):
        return
    await msg.answer("Akkauntni uzasizmi? Userbot o'qish va tarqatish to'xtaydi.",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                         [B(text="❌ Ha, uzish", callback_data="agg:logout_do")],
                         [B(text="Bekor", callback_data="agg:cancel")]]))


@router.callback_query(F.data == "agg:logout_do")
async def on_logout_do(cb: CallbackQuery, bot: Bot):
    global logout_requested
    if not await _admin_cb(cb, bot):
        return
    ub = admin.userbot
    if ub is None:
        try:
            await cb.message.edit_text("Akkaunt allaqachon ulanmagan.")
        except TelegramAPIError:
            pass
        await cb.answer()
        return
    logout_requested = True
    try:
        await ub.log_out()                  # sessiyani serverda ham bekor qiladi
    except Exception as e:
        log.warning("log_out xatosi: %s", e)
    admin.userbot = None
    _delete_session()
    set_active(False)
    try:
        await cb.message.edit_text("✅ Akkaunt uzildi. Userbotsiz ishlash uchun .env da MODE=bot qiling.")
    except TelegramAPIError:
        pass
    await cb.answer()


def _delete_session():
    for suffix in (".session", ".session-journal"):
        p = config.BASE_DIR / (config.SESSION_NAME + suffix)
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Sessiya faylini o'chirib bo'lmadi %s: %s", p, e)
