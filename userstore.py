"""Foydalanuvchi roli (yo'lovchi/haydovchi). users.json da saqlanadi, store.py atomik-JSON naqshida."""
import json
import logging
import os

import config

log = logging.getLogger(__name__)

_users: dict | None = None      # {"<user_id>": {"role": "passenger"|"driver"}}
ROLES = ("passenger", "driver")


def _load() -> dict:
    global _users
    if _users is None:
        try:
            _users = json.loads(config.USERS_FILE.read_text(encoding="utf-8")) if config.USERS_FILE.exists() else {}
        except (OSError, ValueError) as e:
            log.error("%s o'qilmadi (%s)", config.USERS_FILE.name, e)
            _users = {}
    return _users


def _save():
    tmp = config.USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_users, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, config.USERS_FILE)


def get_role(user_id) -> str | None:
    return _load().get(str(user_id), {}).get("role")


def set_role(user_id, role: str):
    if role not in ROLES:
        return
    _load().setdefault(str(user_id), {})["role"] = role
    _save()
