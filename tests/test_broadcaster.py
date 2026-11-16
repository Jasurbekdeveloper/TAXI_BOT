"""Rassilka siklidagi xatolarni ushlash: FloodWait, yozish taqiqlangan guruh, bekor qilingan sessiya."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


class FloodWaitError(Exception):
    def __init__(self, seconds):
        self.seconds = seconds


class ChatWriteForbiddenError(Exception):
    pass


class AuthKeyUnregisteredError(Exception):
    pass


class Client:
    def __init__(self, errors=None):
        self.errors = dict(errors or {})        # chat_id -> [xato, ...] (navbat bilan)
        self.sent = []
        self.disconnected = False

    async def send_message(self, cid, text):
        q = self.errors.get(cid)
        if q:
            raise q.pop(0)
        self.sent.append(cid)

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    from database import crud, models
    from services.broadcaster import Manager
    models.close()
    for k, v in (("DB_FILE", "t.db"), ("USERS_FILE", "u.json"), ("ROUTES_FILE", "r.json")):
        monkeypatch.setattr(config, k, tmp_path / v)
    crud.touch_user(1, None, "A")
    crud.save_session(1, "+998900000000", "enc", 555, None, "Ali")
    crud.sync_groups(1, [(-1, "A"), (-2, "B"), (-3, "C")])
    for c in (-1, -2, -3):
        crud.toggle_group(1, c, 12)
    m = Manager()
    slept = []

    async def sleep(s):
        slept.append(s)
    m.sleep = sleep
    notes = []

    async def notify(uid, text):
        notes.append(text)
    m.notify = notify
    yield SimpleNamespace(m=m, crud=crud, slept=slept, notes=notes)
    models.close()


def run(coro):
    return asyncio.run(coro)


def test_round_skips_forbidden_and_waits_flood(env):
    c = Client({-2: [ChatWriteForbiddenError()], -3: [FloodWaitError(30)]})
    env.m.clients[1] = c
    ok, skipped = run(env.m._round(1, "e'lon", env.crud.selected_groups(1)))
    assert ok == 2 and c.sent == [-1, -3]                       # -3 FloodWait'dan keyin qayta yuborildi
    assert skipped == ["B"] and -2 not in dict(env.crud.selected_groups(1))
    assert 31 in env.slept                                      # FloodWait kutildi
    gaps = [s for s in env.slept if s != 31]
    assert len(gaps) == 2 and all(5 <= s <= 12 for s in gaps)   # guruhlar orasida tasodifiy pauza


def test_round_revoked_session_deleted(env):
    from services.broadcaster import Revoked
    c = Client({-1: [AuthKeyUnregisteredError()]})
    env.m.clients[1] = c
    with pytest.raises(Revoked):
        run(env.m._round(1, "e'lon", env.crud.selected_groups(1)))
    assert env.crud.get_session(1) is None and 1 not in env.m.clients and c.disconnected
    assert env.notes and "bekor" in env.notes[0]


def test_long_flood_stops(env):
    from services.broadcaster import Halt
    env.m.clients[1] = Client({-1: [FloodWaitError(7200)]})
    env.crud.set_running(1, True)
    with pytest.raises(Halt):
        run(env.m._round(1, "e'lon", env.crud.selected_groups(1)))
    assert env.crud.get_session(1) is not None and not env.crud.get_session(1)["is_running"]


def test_can_start_rules(env):
    m, crud = env.m, env.crud
    assert "ulang" in m.can_start(1) or "ruxsat" in m.can_start(1)
    crud.set_unlimited(1, True)
    assert "ulang" in m.can_start(1)
    m.clients[1] = Client()
    assert "matn" in m.can_start(1)
    crud.set_ad_text(1, "Termiz-Toshkent")
    assert m.can_start(1) is None
    crud.set_setting("global_stop", 1)
    assert "to'xtatgan" in m.can_start(1)
    crud.set_setting("global_stop", 0)
    crud.set_blocked(1, True)
    assert "bloklangan" in m.can_start(1)
