"""Haydovchi va yo'lovchi bot orqali yozishadi.

Bot orqali buyurtma bergan yo'lovchiga bot doim yoza oladi, shuning uchun bu yo'l username va
maxfiylik sozlamalariga bog'liq emas. Suhbatlar xotirada turadi, restartda yopiladi.
"""
import logging
import time
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import pipeline

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")

CHAT_TTL_SEC = 24 * 3600


@dataclass
class Chat:
    driver_id: int
    passenger_id: int
    route: str
    updated: float


_by_passenger: dict[int, Chat] = {}     # yo'lovchining bitta haydovchisi bo'ladi
_current: dict[int, int] = {}           # haydovchi -> hozir yozayotgan yo'lovchisi


def _driver_chats(driver_id) -> list[Chat]:
    return [c for c in _by_passenger.values() if c.driver_id == driver_id]


def _close(chat: Chat):
    _by_passenger.pop(chat.passenger_id, None)
    if _current.get(chat.driver_id) == chat.passenger_id:
        rest = _driver_chats(chat.driver_id)
        if rest:
            _current[chat.driver_id] = rest[-1].passenger_id
        else:
            del _current[chat.driver_id]


def _purge():
    now = time.time()
    for chat in [c for c in _by_passenger.values() if now - c.updated > CHAT_TTL_SEC]:
        _close(chat)


def _in_chat(msg: Message) -> bool:
    _purge()
    uid = msg.from_user.id if msg.from_user else None
    return uid in _current or uid in _by_passenger


def _driver_intro(route: str) -> str:
    return (f"💬 Yo'lovchi bilan suhbat ochildi\n📍 {route}\n\n"
            "Shu yerga yozganingiz yo'lovchiga boradi, javobi shu yerga keladi.\n"
            "Yakunlash: /end. Suhbatlar ro'yxati: /chats")


async def connect(bot: Bot, driver_id, passenger_id, route: str, driver_name: str) -> bool:
    """Suhbatni ochadi. Haydovchiga yetkazib bo'lmasa (botni boshlamagan) False qaytaradi."""
    old = _by_passenger.get(passenger_id)
    if old:
        _close(old)
    _by_passenger[passenger_id] = Chat(driver_id, passenger_id, route, time.time())
    _current[driver_id] = passenger_id
    try:
        await bot.send_message(
            passenger_id,
            f"🚕 Buyurtmangizni haydovchi oldi: {driver_name}\n"
            "U qo'ng'iroq qiladi yoki shu yerga yozadi. Bu yerga yozganingiz unga boradi.\n"
            "Yakunlash: /end",
            parse_mode="HTML",
        )
    except TelegramAPIError as e:           # yo'lovchi botni bloklagan bo'lishi mumkin
        log.warning("Yo'lovchiga xabar yetmadi: %s", e)
    try:
        await bot.send_message(driver_id, _driver_intro(route))
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


# ---------- Haydovchi botni "Oldim" dan keyin ochdi ----------
@router.message(CommandStart(magic=F.args == "chat"))
async def on_open(msg: Message):
    passenger_id = _current.get(msg.from_user.id)
    chat = _by_passenger.get(passenger_id)
    await msg.answer(_driver_intro(chat.route) if chat else "Hozir ochiq suhbat yo'q.")


@router.message(Command("end"))
async def on_end(msg: Message, bot: Bot):
    uid = msg.from_user.id
    chat = _by_passenger.get(_current.get(uid)) or _by_passenger.get(uid)
    if not chat:
        await msg.answer("Hozir ochiq suhbat yo'q.")
        return
    other = chat.passenger_id if uid == chat.driver_id else chat.driver_id
    _close(chat)
    await msg.answer("Suhbat yakunlandi.")
    if other != uid:
        try:
            await bot.send_message(other, f"Suhbat yakunlandi\n📍 {chat.route}")
        except TelegramAPIError as e:
            log.warning("Suhbat yakuni yetmadi: %s", e)


def _switch_kb(chat: Chat):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"↩️ Shu yo'lovchiga yozish: {chat.route[:40]}",
                             callback_data=f"relay:{chat.passenger_id}")
    ]])


@router.message(Command("chats"))
async def on_chats(msg: Message):
    chats = _driver_chats(msg.from_user.id)
    if not chats:
        await msg.answer("Hozir ochiq suhbat yo'q.")
        return
    current = _current.get(msg.from_user.id)
    for c in chats:
        mark = "✅ Hozirgi suhbat" if c.passenger_id == current else "Suhbat"
        await msg.answer(f"{mark}\n📍 {c.route}", reply_markup=None if c.passenger_id == current else _switch_kb(c))


@router.callback_query(F.data.regexp(r"^relay:\d+$"))
async def on_switch(cb: CallbackQuery):
    chat = _by_passenger.get(int(cb.data.split(":")[1]))
    if not chat or chat.driver_id != cb.from_user.id:
        await cb.answer("Bu suhbat yopilgan", show_alert=True)
        return
    _current[chat.driver_id] = chat.passenger_id
    await cb.answer(f"Endi: {chat.route}"[:200])


# ---------- Xabarlarni o'tkazish ----------
@router.message(StateFilter(None), _in_chat, ~F.text.startswith("/"))
async def on_relay(msg: Message, bot: Bot):
    uid = msg.from_user.id
    if uid in _current:                     # haydovchi yozdi
        chat = _by_passenger[_current[uid]]
        to, prefix, markup = chat.passenger_id, "🚕 Haydovchi", None
    else:                                   # yo'lovchi yozdi
        chat = _by_passenger[uid]
        to, prefix = chat.driver_id, f"🧍 Yo'lovchi ({chat.route})"
        markup = None if _current.get(to) == uid else _switch_kb(chat)
    chat.updated = time.time()
    try:
        if msg.text:
            await bot.send_message(to, f"{prefix}:\n{msg.text}", reply_markup=markup)
        else:                               # rasm, ovoz, joylashuv. Forward emas: profil ko'rinmaydi
            await bot.send_message(to, f"{prefix}:", reply_markup=markup)
            await msg.copy_to(to)
        pipeline.stats["relayed"] += 1
    except TelegramForbiddenError:
        _close(chat)
        await msg.answer("Xabar yetmadi: u botni bloklagan. Suhbat yopildi.")
    except TelegramBadRequest as e:
        log.warning("Xabarni o'tkazib bo'lmadi: %s", e)
        await msg.answer("Bu xabarni yuborib bo'lmadi.")
