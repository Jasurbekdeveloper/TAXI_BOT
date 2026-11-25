"""Yopiq guruh nazorati: sinov, kunlik eslatma, to'lovsizni chiqarish, to'lovdan keyin havola."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

CHAT = -100777
DAY = 86400


class FakeBot:
    def __init__(self, dm_ok=True):
        self.dm_ok = dm_ok
        self.sent, self.banned, self.unbanned, self.links = [], [], [], []

    async def send_message(self, chat_id, text, **kw):
        from aiogram.exceptions import TelegramForbiddenError
        if chat_id > 0 and not self.dm_ok:
            raise TelegramForbiddenError(method=None, message="bot can't initiate conversation")
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def delete_message(self, *a):
        pass

    async def get_me(self):
        return SimpleNamespace(username="taxibot")

    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=SimpleNamespace(id=900))]

    async def ban_chat_member(self, chat_id, uid):
        self.banned.append((chat_id, uid))

    async def unban_chat_member(self, chat_id, uid, only_if_banned=False):
        self.unbanned.append((chat_id, uid))

    async def create_chat_invite_link(self, chat_id, **kw):
        self.links.append(chat_id)
        return SimpleNamespace(invite_link=f"https://t.me/+inv{chat_id}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from database import crud, models
    from services import membership
    models.close()
    for k, v in (("DB_FILE", "t.db"), ("USERS_FILE", "u.json"), ("ROUTES_FILE", "r.json")):
        monkeypatch.setattr(config, k, tmp_path / v)
    monkeypatch.setattr(config, "DRIVERS_CHAT_ID", CHAT)
    monkeypatch.setattr(config, "ADMIN_IDS", {1})
    membership._chat_admins.clear()
    membership._chat_admins_ts.clear()
    crud.set_setting("member_control", 1)
    yield SimpleNamespace(crud=crud, mem=membership)
    models.close()


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


async def _join(env, bot, uid, now):
    env.crud.touch_user(uid, None, "Ali")
    env.crud.member_join(CHAT, uid, now)
    await env.mem.on_member(bot, CHAT, uid, "Ali", now)


def test_trial_reminders_then_kick(env):
    bot, t0 = FakeBot(), 1_000_000.0
    run(_join(env, bot, 5, t0))
    assert "3 kun bepul" in bot.sent[-1][1]
    assert env.crud.has_access(5, t0)
    # 1-kun, 2-kun, 3-kun: har kuni bitta eslatma
    for day in (0.1, 1.1, 2.1):
        n = len(bot.sent)
        run(env.mem.check(bot, t0 + day * DAY))
        run(env.mem.check(bot, t0 + day * DAY + 3600))       # bir kunda ikkinchi marta yozilmaydi
        assert len(bot.sent) == n + 1 and "tugaydi" in bot.sent[-1][1]
    assert "bugun" in bot.sent[-1][1]
    assert not bot.banned
    res = run(env.mem.check(bot, t0 + 3 * DAY + 60))
    assert res["kicked"] == 1 and bot.banned == [(CHAT, 5)] and bot.unbanned == [(CHAT, 5)]
    assert "chiqarildingiz" in bot.sent[-1][1]
    assert env.crud.kicked_chats(5) == [CHAT]
    # qayta kirsa — sinov ishlatilgan, darhol chiqariladi
    run(_join(env, bot, 5, t0 + 4 * DAY))
    assert len(bot.banned) == 2


def test_paid_gets_link_and_no_reminder(env):
    bot, t0 = FakeBot(), 1_000_000.0
    run(_join(env, bot, 6, t0))
    run(env.mem.check(bot, t0 + 3 * DAY + 60))
    env.crud.add_subscription(6, 30, t0 + 3 * DAY + 100)
    text = run(env.mem.on_paid(bot, 6))
    assert "inv" in text and bot.links == [CHAT]
    env.crud.member_join(CHAT, 6, t0 + 3 * DAY + 200)    # havola orqali qaytdi
    n = len(bot.sent)
    run(env.mem.check(bot, t0 + 4 * DAY))
    assert len(bot.sent) == n and len(bot.banned) == 1


def test_admins_and_disabled_untouched(env):
    bot, t0 = FakeBot(), 1_000_000.0
    for uid in (1, 900):                                  # ADMIN_IDS va guruh admini
        env.crud.touch_user(uid, None, "Adm")
        env.crud.member_join(CHAT, uid, t0)
    run(env.mem.check(bot, t0 + 10 * DAY))
    assert not bot.banned and not bot.sent
    env.crud.set_setting("member_control", 0)
    run(_join(env, bot, 7, t0))
    run(env.mem.check(bot, t0 + 10 * DAY))
    assert not bot.banned


def test_group_fallback_when_dm_closed(env):
    bot, t0 = FakeBot(dm_ok=False), 1_000_000.0
    run(_join(env, bot, 8, t0))
    assert bot.sent[-1][0] == CHAT and "tg://user?id=8" in bot.sent[-1][1]
