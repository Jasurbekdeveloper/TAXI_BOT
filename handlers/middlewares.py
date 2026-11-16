"""Har shaxsiy xabar/tugmada: foydalanuvchini bazaga yozadi (statistika, broadcast, qidirish uchun)
va bloklangan foydalanuvchini to'xtatadi (adminlar bundan mustasno)."""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
from database import crud

log = logging.getLogger(__name__)


class TrackUsers(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]], event: TelegramObject,
                       data: dict) -> Any:
        user = getattr(event, "from_user", None)
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if user is None or chat is None or chat.type != "private" or user.is_bot:
            return await handler(event, data)
        try:
            crud.touch_user(user.id, user.username, user.full_name)
            blocked = crud.is_blocked(user.id) and user.id not in config.ADMIN_IDS
        except Exception as e:          # baza xatosi botni to'xtatmasin
            log.error("Foydalanuvchini yozib bo'lmadi: %s", e)
            return await handler(event, data)
        if blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Siz bloklangansiz", show_alert=True)
            else:
                await event.answer("🚫 Siz bloklangansiz. Admin bilan bog'laning.")
            return None
        return await handler(event, data)
