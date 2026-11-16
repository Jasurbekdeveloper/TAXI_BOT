"""Tugmali boshqaruv paneli: /menu. Guruh/kanal qo'shish, ro'yxat, userbot holati.

Slash buyruqlar (admin.py dagi /addgroup, /groups ...) zaxira sifatida qoladi.
Qo'shishning uch yo'li:
  1. «Guruhga/Kanalga qo'shish» tugmasi — Telegram botni o'zi tanlangan joyga qo'shadi (deep-link).
  2. «Havola bilan qo'shish» — @username, t.me havola yoki ID yuboriladi.
  3. Manba guruh/kanaldagi xabarni shu botga forward qilish.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admin

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
B = InlineKeyboardButton


class AddWatch(StatesGroup):
    waiting = State()


def _menu_kb(bot_username: str) -> InlineKeyboardMarkup:
    # startgroup / startchannel: Telegram botni tanlangan guruh yoki kanalga qo'shadi
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="➕ Guruhga qo'shish", url=f"https://t.me/{bot_username}?startgroup=watch")],
        [B(text="➕ Kanalga qo'shish", url=f"https://t.me/{bot_username}?startchannel&admin=change_info")],
        [B(text="🔗 Havola / forward bilan qo'shish", callback_data="w:add_link")],
        [B(text="📋 Ro'yxat va o'chirish", callback_data="w:list")],
        [B(text="🗂 Yo'nalishlar va yopiq guruhlar", callback_data="w:routes")],
        [B(text="👤 User sifatida o'qish (userbot)", callback_data="w:userbot")],
    ])


async def _show_menu(target: Message, bot: Bot):
    me = await bot.me()
    n = len(__import__("store").all_groups())
    await target.answer(
        f"🚕 <b>Manba guruh/kanallarni boshqarish</b>\nHozir kuzatuvda: {n} ta\n\n"
        "Qo'shishning uch yo'li:\n"
        "• <b>Guruhga/Kanalga qo'shish</b> — botni o'zingiz boshqaradigan joyga qo'shadi\n"
        "• <b>Havola bilan</b> — @username yoki t.me havola yuborasiz\n"
        "• Manba guruh/kanaldagi xabarni shu botga <b>forward</b> qilasiz",
        parse_mode="HTML", reply_markup=_menu_kb(me.username))


@router.message(Command("menu"))
async def on_menu(msg: Message, bot: Bot, state: FSMContext):
    if not await admin.is_admin(bot, msg.from_user.id):
        return
    await state.clear()
    await _show_menu(msg, bot)


@router.callback_query(F.data == "w:menu")
async def on_back(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer()
        return
    await state.clear()
    await _show_menu(cb.message, bot)
    await cb.answer()


@router.callback_query(F.data == "w:list")
async def on_list(cb: CallbackQuery, bot: Bot):
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer("Faqat adminlar uchun", show_alert=True)
        return
    text, kb = admin._groups_view()
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)      # ❌ tugmalarini admin.py qayta ishlaydi
    await cb.answer()


@router.callback_query(F.data == "w:userbot")
async def on_userbot(cb: CallbackQuery, bot: Bot):
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer()
        return
    state = "🟢 yoqilgan" if admin.userbot is not None else "🔴 o'chiq"
    await cb.message.answer(
        "👤 <b>User sifatida o'qish (userbot)</b>\n\n"
        f"Holati: {state}\n\n"
        "Bu rejimda bot manba guruhda bo'lmasa ham, siz obuna bo'lgan guruh va kanallarni "
        "<b>akkaunt o'rnidan</b> o'qiydi. Begona taksi kanallarini kuzatish uchun shu kerak.\n\n"
        "Yoqish:\n"
        "1. my.telegram.org dan <code>API_ID</code> va <code>API_HASH</code> olasiz\n"
        "2. <code>.env</code> da <code>MODE=both</code>, API_ID va API_HASH yozasiz\n"
        "3. Terminalda bir marta telefon raqam va kod bilan kirasiz\n"
        "4. Keyin shu menyudan guruh/kanal qo'shasiz — akkaunt ularga obuna bo'ladi\n\n"
        "⚠️ Diqqat: oddiy akkauntni bot kabi ishlatish Telegram qoidalariga ziddir, "
        "akkaunt bloklanishi mumkin. Alohida, muhim bo'lmagan raqamdan foydalaning.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="⬅️ Orqaga", callback_data="w:menu")]]))
    await cb.answer()


@router.callback_query(F.data == "w:routes")
async def on_routes(cb: CallbackQuery, bot: Bot):
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer("Faqat adminlar uchun", show_alert=True)
        return
    from handlers import admin_panel       # yo'nalishlar endi /admin -> Yo'nalishlar bo'limida
    text, kb = admin_panel.routes_view()
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "w:add_link")
async def on_add_link(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await admin.is_admin(bot, cb.from_user.id):
        await cb.answer("Faqat adminlar uchun", show_alert=True)
        return
    await state.set_state(AddWatch.waiting)
    await cb.message.answer(
        "Guruh yoki kanalning @username, t.me havolasi yoki ID sini yuboring.\n"
        "Yoki o'sha guruh/kanaldagi istalgan xabarni shu yerga <b>forward</b> qiling.\n\n"
        "Bekor qilish: /cancel", parse_mode="HTML")
    await cb.answer()


@router.message(StateFilter(AddWatch.waiting), Command("cancel"))
async def on_cancel(msg: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await _show_menu(msg, bot)


@router.message(StateFilter(AddWatch.waiting))
async def on_receive(msg: Message, bot: Bot, state: FSMContext):
    origin = msg.forward_origin                      # forward qilingan xabarning manbasi
    src = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None) if origin else None
    if src is not None:                              # kanal yoki guruhdan forward
        raw = str(src.id)
    elif msg.text:
        raw = msg.text.strip()
    else:
        await msg.answer("Matn yuboring yoki guruh/kanaldagi xabarni forward qiling. Bekor: /cancel")
        return
    result = await admin.add_watch(bot, raw)
    await state.clear()
    await msg.answer(result)
    await _show_menu(msg, bot)
