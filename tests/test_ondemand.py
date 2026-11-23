"""Haydovchi akkauntlari talab bo'yicha ulanadi: ish vaqtida ulanadi, keyin uziladi; kuzatuvchi doim ulangan."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


class FakeClient:
    made = []

    def __init__(self, s, receive_updates=True):
        self.s, self.receive_updates = s, receive_updates
        self.connected = False
        self.handlers = []
        FakeClient.made.append(self)

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return SimpleNamespace(id=555)

    def add_event_handler(self, h, ev):
        self.handlers.append(h)

    async def disconnect(self):
        self.connected = False


@pytest.fixture
def env(tmp_path, monkeypatch):
    from database import crud, models
    from services import broadcaster, crypto
    models.close()
    for k, v in (("DB_FILE", "t.db"), ("USERS_FILE", "u.json"), ("ROUTES_FILE", "r.json"),
                 ("FERNET_KEY_FILE", "f.key")):
        monkeypatch.setattr(config, k, tmp_path / v)
    monkeypatch.setattr(config, "API_ID", 1)
    monkeypatch.setattr(config, "API_HASH", "x")
    crud.touch_user(1, None, "A")
    crud.save_session(1, "+998900000000", crypto.encrypt("SESS"), 555, None, "Ali")
    FakeClient.made = []
    m = broadcaster.Manager()
    m.factory = FakeClient
    yield SimpleNamespace(m=m, crud=crud)
    models.close()


def run(c):
    return asyncio.run(c)


def test_start_does_not_keep_ordinary_account_online(env):
    run(env.m.start(None))
    assert env.m.is_connected(1) and not env.m.is_live(1)       # akkaunt ulangan, lekin onlayn emas
    assert env.m.tg_ids[1] == 555 and FakeClient.made == []


def test_session_connects_for_job_then_disconnects(env):
    async def go():
        await env.m.start(None)
        async with env.m.session(1) as c:
            assert c is not None and c.connected and env.m.is_live(1)
            assert c.receive_updates is False and c.handlers == []   # vaqtinchalik: o'qimaydi
            async with env.m.session(1) as c2:                     # ichma-ich ish: o'sha client
                assert c2 is c
            assert c.connected                                     # tashqi ish hali tugamagan
        return c
    c = run(go())
    assert not c.connected and not env.m.is_live(1)


def test_watcher_stays_online_and_reads(env):
    env.crud.set_watcher(1, True)

    async def go():
        await env.m.start(None)
        c = env.m.clients[1]
        async with env.m.session(1) as c2:
            assert c2 is c
        return c
    c = run(go())
    assert c.connected and env.m.is_live(1) and len(c.handlers) == 1


def test_disconnect_clears_watcher(env):
    env.crud.set_watcher(1, True)

    async def go():
        await env.m.start(None)
        await env.m.disconnect(1, logout=False)
    run(go())
    assert not env.m.is_connected(1) and not env.crud.is_watcher(1)


def test_key_rotation(env, monkeypatch):
    from cryptography.fernet import Fernet
    from services import crypto
    old = crypto.key_source()
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(config, "SESSION_SECRET", k1)
    crypto.reset()
    env.crud.save_session(1, "+998900000000", crypto.encrypt("SESS2"), 555, None, "Ali")
    monkeypatch.setattr(config, "SESSION_SECRET", f"{k2},{k1}")    # yangi kalit birinchi
    crypto.reset()
    assert crypto.rotate_all() == 1
    monkeypatch.setattr(config, "SESSION_SECRET", k2)              # eski kalit olib tashlandi
    crypto.reset()
    assert crypto.decrypt(env.crud.get_session(1)["session_enc"]) == "SESS2"
    crypto.reset()
    assert old in ("env", "file")


def test_harden_fixes_permissions(tmp_path, monkeypatch):
    import os
    from services import security
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "FERNET_KEY_FILE", tmp_path / "fernet.key")
    monkeypatch.setattr(config, "SESSION_SECRET", "")
    for n in (".env", "userbot.session", "taxi.db", "fernet.key", "ssh-key-1.key"):
        (tmp_path / n).write_text("x")
        os.chmod(tmp_path / n, 0o644)
    warns = security.harden()
    if os.name == "posix":
        assert oct(os.stat(tmp_path / "userbot.session").st_mode & 0o777) == "0o600"
    assert any("fernet.key" in w for w in warns) and any("ssh-key-1.key" in w for w in warns)


def test_broadcast_auto_stops(env, monkeypatch):
    import time as t
    env.crud.sync_groups(1, [(-1, "A")])
    env.crud.toggle_group(1, -1, 12)
    env.crud.set_ad(1, "e'lon") if hasattr(env.crud, "set_ad") else env.crud.conn().execute(
        "UPDATE user_sessions SET ad_text='e''lon' WHERE user_id=1")
    env.crud.grant(1, None) if hasattr(env.crud, "grant") else None
    env.crud.set_setting("broadcast_max_hours", 6)
    env.crud.set_running(1, True)
    env.crud.conn().execute("UPDATE broadcast_started SET ts=? WHERE user_id=1", (t.time() - 7 * 3600,))
    notes = []

    async def notify(uid, text):
        notes.append(text)
    env.m.notify = notify
    monkeypatch.setattr(env.crud, "has_access", lambda uid: True)
    env.m.linked.add(1)
    run(env.m._loop(1))
    assert any("avtomatik o'chirildi" in n for n in notes)
    assert env.crud.get_session(1)["is_running"] == 0 and env.crud.broadcast_started_at(1) is None
