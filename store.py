"""Kuzatiladigan guruhlar ro'yxati. groups.json da saqlanadi, restartdan keyin ham qoladi."""
import json
import logging
import os

import config

log = logging.getLogger(__name__)

_groups: list[dict] | None = None   # {"id": int|None, "username": str|None, "title": str}


def _uname(username) -> str | None:
    return username.lstrip("@").lower() if username else None


def kind_of(g: dict) -> str:
    """"group" yoki "channel". Eski yozuvlarda maydon bo'lmasa guruh deb hisoblanadi."""
    return "channel" if g.get("kind") == "channel" else "group"


def _load() -> list[dict]:
    global _groups
    if _groups is None:
        if config.GROUPS_FILE.exists():
            _groups = json.loads(config.GROUPS_FILE.read_text(encoding="utf-8"))
        else:                               # birinchi ishga tushirish: .env dagi ro'yxatni ko'chiramiz
            _groups = [
                {"id": x, "username": None, "title": ""} if isinstance(x, int)
                else {"id": None, "username": _uname(x), "title": ""}
                for x in config.SOURCE_CHATS
            ]
            _save()
    return _groups


def _save():
    tmp = config.GROUPS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_groups, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, config.GROUPS_FILE)     # yozish yarmida uzilsa, eski fayl buzilmaydi


def _match(g, chat_id, username) -> bool:
    uname = _uname(username)
    return (chat_id is not None and g["id"] == chat_id) or (uname is not None and g["username"] == uname)


def find(chat_id, username=None, title=None) -> dict | None:
    """Guruh ro'yxatda bo'lsa qaytaradi. @username bilan qo'shilganlarning id si shu yerda to'ldiriladi."""
    for g in _load():
        if _match(g, chat_id, username):
            changed = False
            if chat_id is not None and g["id"] != chat_id:
                g["id"], changed = chat_id, True
            if title and g["title"] != title:
                g["title"], changed = title, True
            if changed:
                _save()
            return g
    return None


def add(chat_id, username=None, title="", kind="group") -> bool:
    """Yangi qo'shilsa True, avval bor bo'lsa False."""
    if find(chat_id, username, title):
        return False
    _load().append({"id": chat_id, "username": _uname(username), "title": title or "", "kind": kind})
    _save()
    return True


def remove(chat_id=None, username=None) -> bool:
    groups = _load()
    kept = [g for g in groups if not _match(g, chat_id, username)]
    if len(kept) == len(groups):
        return False
    groups[:] = kept
    _save()
    return True


def migrate(old_id, new_id):
    """Oddiy guruh supergroup ga aylanganda Telegram chat id ni o'zgartiradi."""
    for g in _load():
        if g["id"] == old_id:
            g["id"] = new_id
            _save()


def all_groups() -> list[dict]:
    return list(_load())
