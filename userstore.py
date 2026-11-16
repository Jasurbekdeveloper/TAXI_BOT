"""Foydalanuvchi roli (yo'lovchi/haydovchi). Endi SQLite `users` jadvalida (database/crud.py).

Eski users.json birinchi ishga tushishda avtomatik bazaga ko'chiriladi (database/models.py).
"""
from database import crud

ROLES = ("passenger", "driver")


def get_role(user_id) -> str | None:
    return crud.get_role(int(user_id))


def set_role(user_id, role: str):
    if role not in ROLES:
        return
    crud.set_role(int(user_id), role)
