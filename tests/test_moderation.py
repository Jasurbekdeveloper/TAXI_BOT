import importlib
import sys
import time
from pathlib import Path

import pytest
from aiogram.types import Message

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import moderation as mod


def m(text="", user=None, **extra):
    data = {"message_id": 1, "date": int(time.time()), "chat": {"id": -100111, "type": "supergroup", "title": "G"},
            "from": user or {"id": 5, "is_bot": False, "first_name": "Ali", "username": "ali_taxi"}, "text": text}
    data.update(extra)
    return Message.model_validate(data)


def ent(text, piece, type_):
    return {"type": type_, "offset": text.index(piece), "length": len(piece)}


@pytest.mark.parametrize("text", [
    "Toshkentdan Samarqandga taksi kerak 2 kishi +998901234567 soat 18:30",
    "Pochta bor Qarshiga, 5.5 kg",
    "Yozing: ali@gmail.com",
    "Kanal yo'q, shunchaki savol",
])
def test_clean_messages_pass(text):
    assert mod.ad_reason(m(text)) is None


@pytest.mark.parametrize("text", [
    "Zo'r kanal https://example.com",
    "kiring t.me/reklama_kanal",
    "sayt: arzon-taksi.uz",
    "Kanalimizga obuna bo'ling!",
    "Подпишитесь на канал",
    "Kunlik ishonchli daromad",
])
def test_ad_text_detected(text):
    assert mod.ad_reason(m(text))


def test_mentions():
    own = "Lichkaga yozing @ali_taxi"
    assert mod.ad_reason(m(own, entities=[ent(own, "@ali_taxi", "mention")])) is None
    bot = "Buyurtma: @my_bot"
    assert mod.ad_reason(m(bot, entities=[ent(bot, "@my_bot", "mention")]), "My_Bot") is None
    other = "Obuna: @zor_kanal"
    assert mod.ad_reason(m(other, entities=[ent(other, "@zor_kanal", "mention")])) == "begona @username"


def test_hidden_link_forward_buttons_channel():
    t = "bu yerda"
    assert mod.ad_reason(m(t, entities=[{"type": "text_link", "offset": 0, "length": 2, "url": "https://x.y"}]))
    fwd = {"type": "channel", "chat": {"id": -100777, "type": "channel", "title": "K"}, "message_id": 1, "date": 1}
    assert mod.ad_reason(m("salom", forward_origin=fwd)) == "kanaldan forward"
    user_fwd = {"type": "user", "sender_user": {"id": 9, "is_bot": False, "first_name": "B"}, "date": 1}
    assert mod.ad_reason(m("Toshkentga taksi kerak", forward_origin=user_fwd)) is None
    kb = {"inline_keyboard": [[{"text": "Kirish", "url": "https://x.y"}]]}
    assert mod.ad_reason(m("salom", reply_markup=kb)) == "havolali tugma"
    ch = {"id": -100888, "type": "channel", "title": "Reklama"}
    assert mod.ad_reason(m("salom", sender_chat=ch)) == "kanal nomidan yozilgan"
    own_group = {"id": -100111, "type": "supergroup", "title": "G"}
    assert mod.ad_reason(m("salom", sender_chat=own_group)) is None     # anonim admin


def test_flood_burst_and_repeat():
    mod._recent.clear()
    hits = [mod.flood_hit(1, 1, f"x{i}", now=100 + i * .5) for i in range(7)]
    assert hits == [False] * 5 + [True, True]
    hits = [mod.flood_hit(1, 2, "bir xil", now=t) for t in (0, 30, 60)]
    assert hits == [False, False, True]
    assert not mod.flood_hit(1, 3, "bir xil", now=0)                # boshqa odam
    assert not mod.flood_hit(1, 2, "bir xil", now=500)              # vaqt o'tgach


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MOD_FILE", tmp_path / "moderation.json")
    importlib.reload(mod)
    return mod


def test_settings_persist(store):
    assert store.settings(-1) == store.DEFAULTS
    assert store.toggle(-1, "ads") is False
    store.bump(-1, "joins"); store.bump(-1, "joins")
    importlib.reload(mod)                                            # restart
    assert mod.settings(-1)["ads"] is False and mod.counts(-1)["joins"] == 2
    mod.migrate(-1, -1002)
    assert mod.settings(-1002)["ads"] is False and mod.settings(-1)["ads"] is True
