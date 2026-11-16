import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import store
from ai import clean


@pytest.fixture
def groups(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GROUPS_FILE", tmp_path / "groups.json")
    monkeypatch.setattr(config, "SOURCE_CHATS", [-100123, "@Toshkent_Taksi"])
    importlib.reload(store)
    return store


def test_seed_only_on_first_run_and_survives_restart(groups, monkeypatch):
    assert len(groups.all_groups()) == 2
    assert groups.remove(chat_id=-100123)
    importlib.reload(store)                     # restart
    assert [g["username"] for g in store.all_groups()] == ["toshkent_taksi"]


def test_username_is_case_insensitive_and_id_backfilled(groups):
    g = groups.find(-100555, "TOSHKENT_taksi", "Toshkent")
    assert g and g["id"] == -100555 and g["title"] == "Toshkent"
    assert groups.find(-100555)


def test_add_remove(groups):
    assert groups.add(-100777, None, "Yangi")
    assert not groups.add(-100777, None, "Yangi")
    assert groups.find(-100777)
    assert groups.remove(chat_id=-100777)
    assert not groups.remove(chat_id=-100777)
    assert not groups.find(-100777)


def test_migrate(groups):
    groups.migrate(-100123, -100999)
    assert groups.find(-100999) and not groups.find(-100123)


def test_contact_url():
    from pipeline import contact_url
    assert contact_url("ali", 5) == "https://t.me/ali"
    assert contact_url(None, 5) == "tg://user?id=5"
    assert contact_url(None, -100123) is None       # kanal nomidan yozilgan
    assert contact_url(None, None) is None


@pytest.mark.parametrize("data", [[{"label": "passenger"}], "matn", None, 5])
def test_ai_non_dict_rejected(data):
    assert clean(data) is None


def test_ai_values_sanitized():
    r = clean({"label": "hack", "from": 123, "to": "Buxoro", "seats": "<x>", "time": ["a"]})
    assert r == {"label": "unknown", "confidence": 0.7, "from": None, "to": "Buxoro", "seats": None, "time": None}
    assert clean({"label": "passenger", "seats": "3"})["seats"] == 3
    assert clean({"label": "driver", "confidence": 7})["confidence"] == 1.0          # chegaradan tashqari
    assert clean({"label": "driver", "confidence": "yuqori"})["confidence"] == 0.7


def test_ai_json_parse():
    from ai import parse_json
    assert parse_json('{"label": "driver"}') == {"label": "driver"}
    assert parse_json('Mana javob: ```json\n{"label": "passenger"}\n```') == {"label": "passenger"}
    assert parse_json("json yo'q") is None


def test_ai_ad_sanitized():
    from ai import clean_ad
    d = clean_ad({"from": "Termiz", "stops": ["Angor", 5, ""], "seats": 99, "phones": ["+998901112233"],
                  "pochta": "ha", "ayol": True})
    assert d["stops"] == ["Angor"] and d["seats"] is None and d["phones"] == ["+998901112233"]
    assert d["pochta"] is False and d["ayol"] is True                               # faqat aniq true
