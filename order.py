"""Yo'lovchi bot orqali buyurtma beradi: qayerdan, qayerga, qachon, telefon -> haydovchilar guruhi."""
import asyncio
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import AiogramError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)

import admin
import config
import pipeline
import userstore
from nlp import analyze, canon_city, find_phone, find_route, normalize

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")

CANCEL = "❌ Bekor qilish"
WHEN_CHOICES = ("Hozir", "Bugun", "Ertaga")
_last_order: dict[int, float] = {}      # foydalanuvchi -> oxirgi buyurtma vaqti
_offered: dict[int, float] = {}         # guruhda kimga taklif qilingan
OFFER_EVERY_SEC = 24 * 3600
ORDER_TIMEOUT_SEC = 30


class Order(StatesGroup):
    filling = State()
    confirm = State()


def _start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚕 Taksi buyurtma qilish", callback_data="order:new")
    ]])


def _role_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧍 Yo'lovchiman", callback_data="role:passenger")],
        [InlineKeyboardButton(text="🚕 Haydovchiman", callback_data="role:driver")],
    ])


ROLE_BACK = InlineKeyboardButton(text="⬅️ Rolni o'zgartirish", callback_data="role:back")


def _passenger_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚕 Taksi buyurtma qilish", callback_data="order:new")],
        [ROLE_BACK],
    ])


DRIVER_INFO = (
    "🚕 <b>Haydovchilar uchun</b>\n\n"
    "Yo'lovchi e'lonlari yopiq haydovchilar guruhlariga yig'iladi — har e'lon yo'nalish hashtagi bilan "
    "(masalan <code>#Toshkent_Termiz</code>).\n\n"
    "Akkauntingizni ulasangiz, e'loningizni o'zingiz a'zo bo'lgan guruhlarga avtomatik tarqatish mumkin. "
    "Guruhga qo'shilish va ruxsat uchun admin bilan bog'laning."
)


def _reply_kb(*rows):
    return ReplyKeyboardMarkup(keyboard=[*rows, [KeyboardButton(text=CANCEL)]], resize_keyboard=True)


def _confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data="order:send"),
        InlineKeyboardButton(text="✏️ Qaytadan", callback_data="order:new"),
    ], [InlineKeyboardButton(text=CANCEL, callback_data="order:cancel")]])


def _summary(d: dict) -> str:
    e = html.escape
    lines = [f"📍 {e(d['frm'])} → {e(d['to'])}", f"🕕 {e(d['when'])}"]
    if d.get("seats"):
        lines.append(f"👥 {d['seats']} kishi")
    lines.append(f"📞 {e(d['phone'])}")
    return "\n".join(lines)


async def _ask_next(msg: Message, state: FSMContext):
    """Yetishmayotgan birinchi ma'lumotni so'raydi, hammasi bo'lsa tasdiqlashga o'tadi."""
    d = await state.get_data()
    if not d.get("frm"):
        await state.update_data(ask="frm")
        await msg.answer("📍 Qayerdan ketasiz? Shahar yoki tumanni yozing.", reply_markup=_reply_kb())
    elif not d.get("to"):
        await state.update_data(ask="to")
        await msg.answer("🏁 Qayerga borasiz?", reply_markup=_reply_kb())
    elif not d.get("when"):
        await state.update_data(ask="when")
        buttons = [KeyboardButton(text=x) for x in WHEN_CHOICES]
        await msg.answer("🕕 Qachon ketasiz? Tanlang yoki yozing, masalan: ertaga 18:30",
                         reply_markup=_reply_kb(buttons))
    elif not d.get("phone"):
        await state.update_data(ask="phone")
        await msg.answer(
            "📞 Haydovchi siz bilan bog'lanishi uchun telefon raqamingizni yuboring. "
            "Raqam faqat haydovchilar guruhiga yuboriladi.",
            reply_markup=_reply_kb([KeyboardButton(text="📱 Raqamimni yuborish", request_contact=True)]),
        )
    else:
        await state.set_state(Order.confirm)
        await msg.answer("Ma'lumotlar qabul qilindi.", reply_markup=ReplyKeyboardRemove())
        await msg.answer(f"<b>Buyurtmangizni tekshiring:</b>\n\n{_summary(d)}", parse_mode="HTML",
                         reply_markup=_confirm_kb())


async def _begin(msg: Message, state: FSMContext, prefill: dict | None = None):
    await state.clear()
    await state.set_state(Order.filling)
    await state.update_data(**(prefill or {}))
    await _ask_next(msg, state)


def _prefill(text: str) -> dict:
    """Yo'lovchi birdan "Toshkentdan Denovga ertaga" deb yozsa, shuni qayta so'ramaymiz."""
    p = analyze(text)
    return {"frm": p.frm, "to": p.to, "when": p.when, "seats": p.seats, "phone": p.phone}


def _clean(text: str) -> str:
    return " ".join(text.split())[:60]


# ---------- Boshlash ----------
@router.message(CommandStart())
async def on_start(msg: Message, command: CommandObject, state: FSMContext, bot: Bot):
    await state.clear()
    if command.args == "order":         # deep link ?start=order — to'g'ridan-to'g'ri buyurtma
        await _begin(msg, state)
        return
    text = "Assalomu alaykum! 🚕\nSiz kimsiz?"
    if await admin.is_admin(bot, msg.from_user.id):
        text += "\n\nBoshqaruv: /admin · /menu · /help"
    await msg.answer(text, reply_markup=_role_kb())


async def _edit_or_send(cb: CallbackQuery, text: str, kb, html_=False):
    pm = "HTML" if html_ else None
    try:
        await cb.message.edit_text(text, parse_mode=pm, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(text, parse_mode=pm, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "role:back")
async def on_role_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _edit_or_send(cb, "Assalomu alaykum! 🚕\nSiz kimsiz?", _role_kb())
    await cb.answer()


@router.callback_query(F.data == "role:passenger")
async def on_role_passenger(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    userstore.set_role(cb.from_user.id, "passenger")
    await cb.answer()
    await _edit_or_send(cb, "🧍 Taksi kerakmi? Yo'nalish va vaqtni ayting, buyurtmangizni haydovchilarga "
                            "yuboramiz va ular siz bilan bog'lanadi.", _passenger_kb())


@router.callback_query(F.data == "role:driver")
async def on_role_driver(cb: CallbackQuery, state: FSMContext):
    from handlers import driver_cabinet
    await state.clear()
    userstore.set_role(cb.from_user.id, "driver")
    await cb.answer()
    await _edit_or_send(cb, DRIVER_INFO, None, html_=True)
    await driver_cabinet.show_menu(cb.message, cb.from_user.id)


@router.message(Command("order"))
async def on_order_cmd(msg: Message, state: FSMContext):
    await _begin(msg, state)


@router.message(Command("cancel"))
async def on_cancel_cmd(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Bekor qilindi. Yangi buyurtma: /order", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == CANCEL)
async def on_cancel_button(msg: Message, state: FSMContext):
    await on_cancel_cmd(msg, state)


@router.callback_query(F.data == "order:cancel")
async def on_cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Bekor qilindi. Yangi buyurtma: /order")
    await cb.answer()


@router.callback_query(F.data == "order:new")
async def on_new_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _begin(cb.message, state)


# ---------- Javoblarni yig'ish ----------
@router.message(StateFilter(Order.filling), F.contact)
async def on_contact(msg: Message, state: FSMContext):
    d = await state.get_data()
    if d.get("ask") != "phone":
        await _ask_next(msg, state)
        return
    if msg.contact.user_id != msg.from_user.id:
        await msg.answer("Iltimos, o'zingizning raqamingizni yuboring yoki yozib bering.")
        return
    await state.update_data(phone=find_phone(msg.contact.phone_number) or msg.contact.phone_number)
    await _ask_next(msg, state)


@router.message(StateFilter(Order.filling), F.text, ~F.text.startswith("/"))
async def on_answer(msg: Message, state: FSMContext):
    d = await state.get_data()
    ask, text = d.get("ask"), _clean(msg.text)

    if ask == "phone":
        phone = find_phone(msg.text)
        if not phone:
            await msg.answer("Raqam tushunilmadi. Misol: +998 90 123 45 67")
            return
        await state.update_data(phone=phone)
    elif ask == "when":
        await state.update_data(when=analyze(text).when or text)
    elif ask in ("frm", "to"):
        if len(text) < 2 or not any(ch.isalpha() for ch in text):
            await msg.answer("Joy nomini yozing, masalan: Denov")
            return
        frm, to = find_route(normalize(text))
        if frm and to:                      # bitta javobda ikkalasini yozgan
            await state.update_data(frm=frm, to=to)
        else:
            value = canon_city(text)
            if value == (d.get("frm") if ask == "to" else d.get("to")):
                await msg.answer("Jo'nash va borish joyi bir xil. Boshqa joy yozing.")
                return
            await state.update_data({ask: value})
    await _ask_next(msg, state)


@router.message(StateFilter(Order.confirm), F.text, ~F.text.startswith("/"))
async def on_text_in_confirm(msg: Message):
    await msg.answer("Yuqoridagi tugmalardan birini bosing yoki /cancel yozing.")


# ---------- Yuborish ----------
@router.callback_query(F.data == "order:send", StateFilter(Order.confirm))
async def on_send(cb: CallbackQuery, state: FSMContext):
    user, now = cb.from_user, time.time()
    wait = config.ORDER_COOLDOWN_SEC - (now - _last_order.get(user.id, 0))
    if wait > 0:
        await cb.answer(f"Keyingi buyurtmani {int(wait) + 1} soniyadan keyin yuborish mumkin", show_alert=True)
        return
    d = await state.get_data()
    await state.clear()                     # ikki marta bosilsa, ikkinchisi quyidagi eskirgan handlerga tushadi
    _last_order[user.id] = now
    await cb.answer()
    await cb.message.edit_text(f"⏳ Yuborilmoqda...\n\n{_summary(d)}", parse_mode="HTML")

    done = asyncio.get_running_loop().create_future()
    await pipeline.submit_order(user.id, user.username, user.full_name, d, done)
    log.info("[order] user=%s %s→%s", user.id, d["frm"], d["to"])
    try:
        ok = await asyncio.wait_for(asyncio.shield(done), ORDER_TIMEOUT_SEC)
    except asyncio.TimeoutError:            # navbat uzun: baribir yuboriladi
        ok = True
    if ok:
        await cb.message.edit_text(
            f"✅ <b>Buyurtmangiz haydovchilarga yuborildi.</b>\n\n{_summary(d)}\n\n"
            "Haydovchi olgach, shu yerga xabar keladi va u siz bilan bog'lanadi.",
            parse_mode="HTML",
        )
    else:
        _last_order.pop(user.id, None)
        await cb.message.edit_text("❌ Yuborib bo'lmadi. Birozdan keyin /order orqali qayta urinib ko'ring.")


@router.callback_query(F.data == "order:send")
async def on_send_stale(cb: CallbackQuery):
    await cb.answer("Bu buyurtma eskirgan. Yangisi: /order", show_alert=True)


# ---------- Oddiy xabar: boshlashni taklif qilish ----------
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_free_text(msg: Message, state: FSMContext):
    prefill = _prefill(msg.text)
    if prefill["frm"] or prefill["to"]:
        await _begin(msg, state, prefill)
    else:
        await msg.answer("Taksi buyurtma qilish uchun tugmani bosing:", reply_markup=_start_kb())


# ---------- Manba guruhlarda taklif (OFFER_IN_GROUPS=1) ----------
async def offer_in_group(msg: Message, bot: Bot):
    """Yo'lovchi xabariga javoban botga o'tish tugmasini yuboradi, bir odamga kuniga 1 marta."""
    user_id, now = msg.from_user.id, time.time()
    if now - _offered.get(user_id, 0) < OFFER_EVERY_SEC:
        return
    _offered[user_id] = now
    try:
        me = await bot.me()
        await msg.reply(
            "🚕 Bot orqali buyurtma bersangiz, haydovchilar o'zlari siz bilan bog'lanadi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Buyurtma berish", url=f"https://t.me/{me.username}?start=order")
            ]]),
        )
    except AiogramError as e:               # guruhda yozish taqiqlangan bo'lishi mumkin
        log.warning("Guruhda taklif yuborilmadi (%s): %s", msg.chat.title, e)
