import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import pipeline


def test_route_hashtag():
    assert pipeline.route_hashtag("Toshkent", "Termiz") == "#Toshkent_Termiz"
    assert pipeline.route_hashtag("Qumqo'rg'on", "Samarqand") == "#Qumqorgon_Samarqand"   # apostrof tushadi
    assert pipeline.route_hashtag("Toshkent", None) == "#Toshkent"
    assert pipeline.route_hashtag(None, "Termiz") == "#Termiz"
    assert pipeline.route_hashtag(None, None) == ""


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROUTES_FILE", tmp_path / "r.json")
    monkeypatch.setattr(config, "ROUTE_FILTER_STRICT", False)
    import routes
    importlib.reload(routes)
    return routes


def test_routes_add_remove_bidirectional(rt):
    assert rt.allowed("Toshkent", "Termiz")                 # ro'yxat bo'sh: hammasi o'tadi
    assert rt.add("termiz", "toshkent")                     # kichik harf -> kanonik
    assert not rt.add("Toshkent", "Termiz")                 # tartibsiz dublikat
    assert rt.allowed("Toshkent", "Termiz")
    assert rt.allowed("Termiz", "Toshkent")                 # ikki tomonlama
    assert not rt.allowed("Samarqand", "Buxoro")            # xizmatsiz yo'nalish
    assert rt.all_routes() and set(rt.all_routes()[0]) == {"Termiz", "Toshkent"}
    assert rt.remove("Toshkent", "Termiz")
    assert not rt.all_routes()
    assert not rt.add("Shaharyoq", "Toshkent")              # tanilmagan shahar


def test_routes_unknown_direction(rt, monkeypatch):
    rt.add("Termiz", "Toshkent")
    assert rt.allowed(None, "Toshkent")                     # noaniq + strict emas -> o'tadi
    monkeypatch.setattr(config, "ROUTE_FILTER_STRICT", True)
    assert not rt.allowed(None, "Toshkent")                 # strict -> o'tmaydi


def test_parse_pair(rt):
    assert rt.parse_pair("Termiz-Toshkent") == ("Termiz", "Toshkent")
    assert rt.parse_pair("Termiz Toshkent") == ("Termiz", "Toshkent")
    assert rt.parse_pair("Termiz → Toshkent") == ("Termiz", "Toshkent")
    assert rt.parse_pair("Termiz") is None
    assert rt.parse_pair("a b c") is None


@pytest.fixture
def us(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "u.json")
    import userstore
    importlib.reload(userstore)
    return userstore


def test_user_role_persist(us):
    assert us.get_role(5) is None
    us.set_role(5, "driver")
    assert us.get_role(5) == "driver"
    importlib.reload(us)                                     # restart: fayldan o'qiladi
    assert us.get_role(5) == "driver"
    us.set_role(5, "passenger")
    assert us.get_role(5) == "passenger"
    us.set_role(5, "boshqa")                                 # noto'g'ri rol e'tiborsiz
    assert us.get_role(5) == "passenger"
