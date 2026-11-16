import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


@pytest.fixture
def db(tmp_path, monkeypatch):
    from database import crud, models
    from services import crypto
    models.close()
    crypto.reset()
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "t.db")
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "u.json")
    monkeypatch.setattr(config, "ROUTES_FILE", tmp_path / "r.json")
    monkeypatch.setattr(config, "FERNET_KEY_FILE", tmp_path / "fernet.key")
    monkeypatch.setattr(config, "SESSION_SECRET", "")
    yield crud
    models.close()
    crypto.reset()


def test_user_search_and_block(db):
    db.touch_user(10, "Ali_Driver", "Ali Valiyev")
    assert db.find_user("@ali_driver")["user_id"] == 10       # username registrsiz
    assert db.find_user("10")["full_name"] == "Ali Valiyev"
    assert db.find_user("@yoq") is None
    db.set_blocked(10, True)
    assert db.is_blocked(10) and 10 not in db.all_user_ids()


def test_subscription(db):
    db.touch_user(1, None, "A")
    now = 1_000_000
    assert not db.has_access(1, now=now)
    db.add_subscription(1, 7, now=now)
    assert db.has_access(1, now=now + 6 * 86400)
    assert not db.has_access(1, now=now + 8 * 86400)
    db.add_subscription(1, 30, now=now + 86400)                # tugamagan obuna oxiridan uzayadi
    assert db.get_user(1)["sub_until"] == now + 37 * 86400
    db.set_blocked(1, True)
    assert not db.has_access(1, now=now)                        # blok ruxsatdan ustun
    db.set_blocked(1, False)
    db.revoke_subscription(1)
    assert not db.has_access(1, now=now)
    db.set_unlimited(1, True)
    assert db.has_access(1, now=now + 10**9)


def test_groups_select_and_limit(db):
    db.touch_user(1, None, "A")
    db.save_session(1, "+998900000000", "enc", 555, "drv", "Ali")
    db.sync_groups(1, [(-1, "A"), (-2, "B"), (-3, "C")])
    assert db.toggle_group(1, -1, limit=2) == "on"
    assert db.toggle_group(1, -2, limit=2) == "on"
    assert db.toggle_group(1, -3, limit=2) == "limit"
    assert db.toggle_group(1, -1, limit=2) == "off"
    assert db.toggle_group(1, -9, limit=2) == "missing"
    db.sync_groups(1, [(-2, "B2"), (-3, "C")])                  # -1 chiqib ketdi, -2 tanlovi saqlanadi
    assert db.selected_groups(1) == [(-2, "B2")]
    assert db.all_selected_chat_ids() == {1: {-2}}
    db.delete_session(1)                                        # guruhlar ham o'chadi (CASCADE)
    assert db.groups(1) == []


def test_settings_defaults(db):
    assert db.get_setting("max_groups") == 12 and db.get_setting("min_gap_sec") == 5
    db.set_setting("max_groups", 8)
    assert db.get_setting("max_groups") == 8
    with pytest.raises(KeyError):
        db.set_setting("nomalum", 1)


def test_rounds_and_report(db):
    db.touch_user(1, None, "A")
    db.save_session(1, "+998900000000", "enc", 555, "drv", "Ali")
    db.sync_groups(1, [(-1, "Termiz"), (-2, "Denov")])
    t = 1_700_000_000
    assert db.start_round(1, now=t) == 1 and db.start_round(1, now=t + 60) == 2
    assert db.rounds_today(1, now=t + 120) == 2
    assert db.rounds_today(1, now=t + 2 * 86400) == 0
    db.record_post(1, -1, now=t); db.record_post(1, -1, now=t); db.record_post(1, -2, now=t)
    assert db.report(1, now=t + 10) == [("Termiz", 2), ("Denov", 1)]
    assert db.report(1, now=t + 86400 + 10) == []


def test_session_encryption(db):
    from services import crypto
    enc = crypto.encrypt("1Aabc-session")
    assert enc != "1Aabc-session" and crypto.decrypt(enc) == "1Aabc-session"
    assert config.FERNET_KEY_FILE.exists()                      # kalit fayli yaratildi
    crypto.reset()
    assert crypto.decrypt(enc) == "1Aabc-session"                # restartdan keyin ham shu kalit
    config.FERNET_KEY_FILE.write_bytes(__import__("cryptography.fernet", fromlist=["F"]).Fernet.generate_key())
    crypto.reset()
    assert crypto.decrypt(enc) is None                           # boshqa kalit: ochilmaydi, xato bermaydi


def test_auth_helpers():
    from services import userbot_auth as a
    assert a.normalize_phone("+998 90 123-45-67") == "+998901234567"
    assert a.normalize_phone("901234567") == "+998901234567"
    assert a.normalize_phone("12") is None
    assert a.clean_code("1 2 3 4 5") == "12345"
