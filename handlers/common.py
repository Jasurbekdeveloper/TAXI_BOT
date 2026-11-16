"""Umumiy yordamchilar: «👤 Admin bilan bog'lanish» tugmasi."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database import crud


def admin_username() -> str | None:
    """.env dagi ADMIN_USERNAME, bo'lmasa ADMIN_IDS dagi birinchi adminning bazadagi @username i."""
    if config.ADMIN_USERNAME:
        return config.ADMIN_USERNAME
    for uid in sorted(config.ADMIN_IDS):
        row = crud.get_user(uid)
        if row and row["username"]:
            return row["username"]
    return None


def admin_url() -> str | None:
    # tg://user?id= ishlatilmaydi: admin maxfiylik sozlamasi bo'lsa Telegram butun xabarni rad etadi
    u = admin_username()
    return f"https://t.me/{u}" if u else None


def contact_button() -> InlineKeyboardButton | None:
    url = admin_url()
    return InlineKeyboardButton(text="👤 Admin bilan bog'lanish", url=url) if url else None


def contact_kb(*rows) -> InlineKeyboardMarkup | None:
    """Berilgan qatorlar + oxirida bog'lanish tugmasi. Hech narsa bo'lmasa None."""
    btn = contact_button()
    kb = [list(r) for r in rows] + ([[btn]] if btn else [])
    return InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
