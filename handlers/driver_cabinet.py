"""Haydovchi kabineti: akkauntni ulash (FSM), guruhlarni tanlash, e'lon matni, interval, tarqatish.

Kirish: /driver yoki /start -> «🚕 Haydovchiman». Asosiy tugmalar pastdan (reply), tanlash — inline.
Callback prefiksi: "dc:".
"""
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

import config
from database import crud
from services import userbot_auth as auth
from services.broadcaster import manager

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
B = InlineKeyboardButton
PAGE = 8
INTERVALS = (15, 30, 60)

BTN_CONNECT = "🔐 Akkauntni ulash"
BTN_GROUPS = "📋 Guruhlarni tanlash"
BTN_TEXT = "✍️ E'lon matni"
BTN_INTERVAL = "⏱ Interval"
BTN_START = "🚀 Tarqatishni boshlash"
BTN_STOP = "🛑 To'xtatish"
BTN_REPORT = "📊 Hisobot"
BTN_ACCOUNT = "👤 Akkaunt"
BTN_HELP = "❓ Yordam"
BTN_ROLE = "⬅️ Rolni o'zgartirish"
BTN_CANCEL = "❌ Bekor qilish"


class Auth(StatesGroup):
    phone = State()
    code = State()
    password = State()


class AdText(StatesGroup):
    waiting = State()


HELP_TEXT = (
    "🚕 <b>Haydovchi kabineti</b>\n\n"
    "1. <b>🔐 Akkauntni ulash</b> — Telegram akkauntingizga bot ichida kirasiz (telefon, kod, kerak bo'lsa parol).\n"
    "2. <b>📋 Guruhlarni tanlash</b> — akkauntingiz a'zo bo'lgan taksi guruhlardan ✅ qilasiz.\n"
    "3. <b>✍️ E'lon matni</b> — masalan: «Termiz → Toshkent, bugun 18:00, 3 joy bor, +998...».\n"
    "4. <b>🚀 Tarqatishni boshlash</b> — e'lon tanlangan guruhlarga navbat bilan, interval bo'yicha takror chiqadi.\n\n"
    "Tanlangan guruhlardagi yo'lovchi e'lonlari esa avtomatik yopiq haydovchilar guruhiga tushadi.\n\n"
    "⚠️ E'lonlar sizning akkauntingiz nomidan yuboriladi. Juda tez-tez yuborish yoki guruh qoidalarini "
    "buzish akkauntni cheklatishi mumkin. Rassilka uchun admin ruxsati (obuna) kerak."
)


# ---------- Ko'rinish ----------
def _menu_kb(uid: int) -> ReplyKeyboardMarkup:
    if not manager.is_connected(uid):
        rows = [[KeyboardButton(text=BTN_CONNECT)], [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_ROLE)]]
    else:
        run = BTN_STOP if manager.is_running(uid) else BTN_START
        rows = [
            [KeyboardButton(text=BTN_GROUPS), KeyboardButton(text=BTN_TEXT)],
            [KeyboardButton(text=run)],
            [KeyboardButton(text=BTN_INTERVAL), KeyboardButton(text=BTN_REPORT)],
            [KeyboardButton(text=BTN_ACCOUNT), KeyboardButton(text=BTN_HELP)],
            [KeyboardButton(text=BTN_ROLE)],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _menu_text(uid: int) -> str:
    sub = crud.sub_text(crud.get_user(uid))
    if not manager.is_connected(uid):
        return ("🚕 <b>Haydovchi kabineti</b>\n\n"
                f"Akkaunt: 🔴 ulanmagan\nRuxsat: {sub}\n\n"
                "Boshlash uchun «🔐 Akkauntni ulash» ni bosing 👇")
    row = crud.get_session(uid)
    n_sel = len(crud.selected_groups(uid))
    run = "🟢 ishlayapti" if manager.is_running(uid) else "🔴 to'xtagan"
    acc = html.escape(row["tg_name"] or "") + (f" (@{html.escape(row['tg_username'])})" if row["tg_username"] else "")
    return ("🚕 <b>Haydovchi kabineti</b>\n\n"
            f"Akkaunt: 🟢 {acc}\nRuxsat: {sub}\n"
            f"Tanlangan guruhlar: {n_sel}/{crud.get_setting('max_groups')}\n"
            f"E'lon matni: {'bor' if row['ad_text'] else 'yoʻq'}\n"
            f"Interval: {row['interval_min']} daqiqa\nRassilka: {run}")


async def show_menu(target: Message, uid: int):
    await target.answer(_menu_text(uid), parse_mode="HTML", reply_markup=_menu_kb(uid))


def _cancel_kb(*extra) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[*extra, [KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


@router.message(Command("driver"))
async def on_driver_cmd(msg: Message, state: FSMContext):
    await state.clear()
    crud.set_role(msg.from_user.id, "driver")
    await show_menu(msg, msg.from_user.id)


@router.message(F.text == BTN_HELP)
async def on_help(msg: Message):
    await msg.answer(HELP_TEXT, parse_mode="HTML", reply_markup=_menu_kb(msg.from_user.id))


@router.message(F.text == BTN_ROLE)
async def on_role(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Menyu yopildi.", reply_markup=ReplyKeyboardRemove())
    await msg.answer("Siz kimsiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🧍 Yo'lovchiman", callback_data="role:passenger")],
        [B(text="🚕 Haydovchiman", callback_data="role:driver")]]))


# ---------- Avtorizatsiya (FSM) ----------
@router.message(F.text == BTN_CONNECT)
async def on_connect(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if manager.is_connected(uid):
        await show_menu(msg, uid)
        return
    if not (config.API_ID and config.API_HASH):
        await msg.answer("⚙️ Akkaunt ulash hozircha sozlanmagan (API_ID/API_HASH). Admin bilan bog'laning.")
        return
    await state.set_state(Auth.phone)
    await msg.answer(
        "📱 Telegram akkauntingiz telefon raqamini yuboring: <code>+998901234567</code>\n\n"
        "Pastdagi tugma faqat <b>shu</b> akkaunt raqamini yuboradi. Boshqa akkauntni ulamoqchi bo'lsangiz, "
        "raqamni yozib yuboring.",
        parse_mode="HTML",
        reply_markup=_cancel_kb([KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]))


@router.message(StateFilter(Auth.phone, Auth.code, Auth.password, AdText.waiting), F.text == BTN_CANCEL)
@router.message(StateFilter(Auth.phone, Auth.code, Auth.password, AdText.waiting), Command("cancel"))
async def on_cancel(msg: Message, state: FSMContext):
    await auth.cancel(msg.from_user.id)
    await state.clear()
    await msg.answer("Bekor qilindi.")
    await show_menu(msg, msg.from_user.id)


@router.message(StateFilter(Auth.phone))
async def on_phone(msg: Message, state: FSMContext):
    raw = msg.contact.phone_number if msg.contact else (msg.text or "")
    phone = auth.normalize_phone(raw)
    if not phone:
        await msg.answer("Raqam tushunilmadi. Misol: +998901234567")
        return
    wait = await msg.answer("⏳ Telegramga so'rov yuborilmoqda...")
    res = await auth.send_code(msg.from_user.id, phone)
    try:
        await wait.delete()
    except TelegramAPIError:
        pass
    if res == "ok":
        await state.set_state(Auth.code)
        await msg.answer(
            "✉️ Telegram ilovangizdagi <b>«Telegram»</b> rasmiy chatiga 5 xonali kod keldi.\n\n"
            "❗️ Kodni <b>bo'sh joy bilan</b> yozing, masalan: <code>1 2 3 4 5</code>\n"
            "Kodni bo'sh joysiz yuborsangiz, Telegram uni «boshqa odamga berilgan» deb bloklaydi va "
            "kirish bekor bo'ladi.",
            parse_mode="HTML", reply_markup=_cancel_kb())
        return
    errors = {
        "invalid_phone": "❌ Bu raqam Telegramda topilmadi yoki noto'g'ri. Qayta yuboring.",
        "banned": "❌ Bu raqam Telegram tomonidan bloklangan.",
        "no_api": "⚙️ Akkaunt ulash sozlanmagan. Admin bilan bog'laning.",
    }
    if res.startswith("flood:"):
        await msg.answer(f"⏳ Juda ko'p urinish. {int(res[6:]) // 60 + 1} daqiqadan keyin qayta urinib ko'ring.")
        await state.clear()
        await show_menu(msg, msg.from_user.id)
        return
    await msg.answer(errors.get(res, "❌ Kod yuborib bo'lmadi. Birozdan keyin qayta urinib ko'ring."))
    if res != "invalid_phone":
        await state.clear()
        await show_menu(msg, msg.from_user.id)


async def _delete_secret(msg: Message):
    """Kod va parol chatda qolmasin."""
    try:
        await msg.delete()
    except TelegramAPIError:
        pass


@router.message(StateFilter(Auth.code))
async def on_code(msg: Message, state: FSMContext):
    code = auth.clean_code(msg.text)
    await _delete_secret(msg)
    if not 4 <= len(code) <= 6:
        await msg.answer("Kodni raqamlar bilan, bo'sh joy qo'yib yozing: 1 2 3 4 5")
        return
    res = await auth.submit_code(msg.from_user.id, code)
    await _after_login_step(msg, state, res)


@router.message(StateFilter(Auth.password))
async def on_password(msg: Message, state: FSMContext):
    pw = msg.text or ""
    await _delete_secret(msg)
    res = await auth.submit_password(msg.from_user.id, pw)
    await _after_login_step(msg, state, res)


async def _after_login_step(msg: Message, state: FSMContext, res: str):
    uid = msg.from_user.id
    if res == "ok":
        await state.clear()
        crud.set_role(uid, "driver")
        await msg.answer("✅ Akkaunt ulandi! Endi «📋 Guruhlarni tanlash» ni bosing.")
        await show_menu(msg, uid)
    elif res == "password":
        await state.set_state(Auth.password)
        await msg.answer("🔑 Akkauntda ikki bosqichli himoya (2FA) bor. Parolni yuboring.\n"
                         "Xabar o'qilgach darhol o'chiriladi.", reply_markup=_cancel_kb())
    elif res == "invalid":
        await msg.answer("❌ Noto'g'ri. Qayta yuboring yoki «❌ Bekor qilish».")
    elif res == "expired":
        await state.clear()
        await msg.answer("⌛ Kod eskirdi yoki Telegram uni blokladi (bo'sh joysiz yuborilgan bo'lishi mumkin). "
                         "Qaytadan «🔐 Akkauntni ulash» ni bosing.")
        await show_menu(msg, uid)
    else:
        await state.clear()
        await msg.answer("❌ Kirib bo'lmadi. Qaytadan urinib ko'ring.")
        await show_menu(msg, uid)


# ---------- Guruhlarni tanlash (sahifalangan) ----------
def _groups_view(uid: int, page: int):
    rows = crud.groups(uid)
    limit = crud.get_setting("max_groups")
    n_sel = sum(1 for r in rows if r["selected"])
    pages = max(1, (len(rows) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    kb = [[B(text=f"{'✅' if r['selected'] else '⬜'} {(r['title'] or str(r['chat_id']))[:40]}",
             callback_data=f"dc:g:{r['chat_id']}:{page}")]
          for r in rows[page * PAGE:(page + 1) * PAGE]]
    nav = []
    if page > 0:
        nav.append(B(text="⬅️", callback_data=f"dc:p:{page - 1}"))
    if pages > 1:
        nav.append(B(text=f"{page + 1}/{pages}", callback_data="dc:noop"))
    if page < pages - 1:
        nav.append(B(text="➡️", callback_data=f"dc:p:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([B(text="🔄 Yangilash", callback_data="dc:refresh"), B(text="💾 Saqlash", callback_data="dc:done")])
    text = (f"📋 <b>Guruhlarni tanlang</b> — {n_sel}/{limit}\n\n"
            "✅ belgilangan guruhlarga e'loningiz yuboriladi, ulardagi yo'lovchi e'lonlari esa yopiq "
            "haydovchilar guruhiga tushadi.")
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


async def _load_groups(uid: int) -> bool:
    try:
        items = await manager.list_groups(uid)
    except Exception as e:
        log.error("Dialoglar olinmadi user=%s: %s", uid, e)
        return False
    crud.sync_groups(uid, items)
    manager.refresh_selected(uid)
    return True


@router.message(F.text == BTN_GROUPS)
async def on_groups(msg: Message):
    uid = msg.from_user.id
    if not manager.is_connected(uid):
        await show_menu(msg, uid)
        return
    wait = await msg.answer("⏳ Guruhlar olinmoqda...")
    ok = await _load_groups(uid)
    try:
        await wait.delete()
    except TelegramAPIError:
        pass
    if not ok:
        await msg.answer("❌ Guruhlar ro'yxatini olib bo'lmadi. Birozdan keyin urinib ko'ring.")
        return
    if not crud.groups(uid):
        await msg.answer("Akkauntingiz hali hech qanday guruhga a'zo emas. Avval taksi guruhlariga qo'shiling.")
        return
    text, kb = _groups_view(uid, 0)
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


async def _edit(cb: CallbackQuery, text: str, kb):
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramAPIError:
        pass


@router.callback_query(F.data.startswith("dc:g:"))
async def on_group_toggle(cb: CallbackQuery):
    uid = cb.from_user.id
    _, _, cid, page = cb.data.split(":")
    res = crud.toggle_group(uid, int(cid), crud.get_setting("max_groups"))
    manager.refresh_selected(uid)
    if res == "limit":
        await cb.answer(f"Ko'pi bilan {crud.get_setting('max_groups')} ta guruh tanlash mumkin", show_alert=True)
        return
    text, kb = _groups_view(uid, int(page))
    await _edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("dc:p:"))
async def on_group_page(cb: CallbackQuery):
    text, kb = _groups_view(cb.from_user.id, int(cb.data[5:]))
    await _edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "dc:refresh")
async def on_group_refresh(cb: CallbackQuery):
    await _load_groups(cb.from_user.id)
    text, kb = _groups_view(cb.from_user.id, 0)
    await _edit(cb, text, kb)
    await cb.answer("Yangilandi")


@router.callback_query(F.data == "dc:done")
async def on_group_done(cb: CallbackQuery):
    n = len(crud.selected_groups(cb.from_user.id))
    await _edit(cb, f"💾 Saqlandi. Tanlangan guruhlar: {n}", None)
    await cb.answer("Saqlandi")


@router.callback_query(F.data == "dc:noop")
async def on_noop(cb: CallbackQuery):
    await cb.answer()


# ---------- E'lon matni ----------
@router.message(F.text == BTN_TEXT)
async def on_text_btn(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    row = crud.get_session(uid)
    if row is None:
        await show_menu(msg, uid)
        return
    await state.set_state(AdText.waiting)
    cur = f"Joriy matn:\n\n<i>{html.escape(row['ad_text'])}</i>\n\n" if row["ad_text"] else ""
    await msg.answer(cur + "Yangi e'lon matnini yuboring (yo'nalish, vaqt, joy soni, telefon).",
                     parse_mode="HTML", reply_markup=_cancel_kb())


@router.message(StateFilter(AdText.waiting))
async def on_text_set(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    if not text:
        await msg.answer("Matn yuboring yoki «❌ Bekor qilish».")
        return
    if len(text) > 1000:
        await msg.answer("Matn juda uzun (1000 belgigacha).")
        return
    crud.set_ad_text(msg.from_user.id, text)
    await state.clear()
    await msg.answer("✅ E'lon matni saqlandi.")
    await show_menu(msg, msg.from_user.id)


# ---------- Interval ----------
def _interval_kb(uid: int) -> InlineKeyboardMarkup:
    cur = crud.get_session(uid)["interval_min"]
    low = crud.get_setting("min_interval_min")
    opts = [m for m in INTERVALS if m >= low] or [low]
    return InlineKeyboardMarkup(inline_keyboard=[[
        B(text=f"{'• ' if m == cur else ''}{m} daq", callback_data=f"dc:i:{m}") for m in opts]])


@router.message(F.text == BTN_INTERVAL)
async def on_interval(msg: Message):
    uid = msg.from_user.id
    if crud.get_session(uid) is None:
        await show_menu(msg, uid)
        return
    await msg.answer("⏱ E'lon har necha daqiqada takrorlansin?", reply_markup=_interval_kb(uid))


@router.callback_query(F.data.startswith("dc:i:"))
async def on_interval_set(cb: CallbackQuery):
    uid, m = cb.from_user.id, int(cb.data[5:])
    if crud.get_session(uid) is None or m < crud.get_setting("min_interval_min"):
        await cb.answer("Mumkin emas", show_alert=True)
        return
    crud.set_interval(uid, m)
    await _edit(cb, f"⏱ Interval: {m} daqiqa. Keyingi sikldan boshlab amal qiladi.", None)
    await cb.answer()


# ---------- Tarqatish ----------
@router.message(F.text == BTN_START)
async def on_start_broadcast(msg: Message):
    uid = msg.from_user.id
    reason = manager.start_broadcast(uid)
    if reason:
        await msg.answer(reason, reply_markup=_menu_kb(uid))
        return
    n = len(crud.selected_groups(uid))
    await msg.answer(f"🚀 Rassilka boshlandi: {n} ta guruh, har {crud.get_session(uid)['interval_min']} daqiqada.\n"
                     "Guruhlar orasida tasodifiy pauza bor — birinchi sikl bir necha daqiqa davom etadi.",
                     reply_markup=_menu_kb(uid))


@router.message(F.text == BTN_STOP)
async def on_stop_broadcast(msg: Message):
    uid = msg.from_user.id
    manager.stop_broadcast(uid)
    await msg.answer("🛑 Rassilka to'xtatildi.", reply_markup=_menu_kb(uid))


@router.message(F.text == BTN_REPORT)
async def on_report(msg: Message):
    uid = msg.from_user.id
    rows = crud.report(uid)
    if not rows:
        await msg.answer("📊 Oxirgi 24 soatda e'lon chiqmadi.", reply_markup=_menu_kb(uid))
        return
    total = sum(n for _, n in rows)
    lines = [f"📊 <b>Oxirgi 24 soat: {total} ta e'lon</b>", ""]
    lines += [f"• {html.escape(t)}: {n}" for t, n in rows]
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=_menu_kb(uid))


# ---------- Akkaunt ----------
@router.message(F.text == BTN_ACCOUNT)
async def on_account(msg: Message):
    uid = msg.from_user.id
    row = crud.get_session(uid)
    if row is None:
        await show_menu(msg, uid)
        return
    phone = row["phone"] or ""
    masked = phone[:6] + "***" + phone[-2:] if len(phone) > 8 else phone
    await msg.answer(
        f"👤 <b>Ulangan akkaunt</b>\n{html.escape(row['tg_name'] or '')}"
        + (f" @{html.escape(row['tg_username'])}" if row["tg_username"] else "")
        + f"\n📞 {masked}\nRuxsat: {crud.sub_text(crud.get_user(uid))}",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [B(text="🔌 Akkauntni uzish", callback_data="dc:logout")]]))


@router.callback_query(F.data == "dc:logout")
async def on_logout(cb: CallbackQuery):
    await _edit(cb, "Akkauntni uzasizmi? Rassilka to'xtaydi va sessiya o'chiriladi.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [B(text="🔌 Ha, uzish", callback_data="dc:logout_do")],
                    [B(text="Bekor", callback_data="dc:logout_no")]]))
    await cb.answer()


@router.callback_query(F.data == "dc:logout_no")
async def on_logout_no(cb: CallbackQuery):
    await _edit(cb, "Bekor qilindi.", None)
    await cb.answer()


@router.callback_query(F.data == "dc:logout_do")
async def on_logout_do(cb: CallbackQuery):
    uid = cb.from_user.id
    await manager.disconnect(uid, logout=True)
    await _edit(cb, "✅ Akkaunt uzildi, sessiya o'chirildi.", None)
    await cb.answer()
    await show_menu(cb.message, uid)
