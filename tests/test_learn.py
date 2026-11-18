"""O'rganuvchi belgilar (services/learn) va AI backend fallback (config.ai_backends)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from services import learn


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEARN_FILE", tmp_path / "learned.json")
    learn.reset()
    yield
    learn.reset()


# Haydovchilar e'lonida uchraydigan o'ziga xos belgilar (emoji + so'zlar)
DRIVER_ADS = [
    "🏘 Termiz 🏘 Angor 🏘 Sheroboddan ➡️ Samarqandga ketamiz 📦 pochta olamiz",
    "🏘 Denov 🏘 Qumqurgon ➡️ Toshkentga ketamiz 📦 pochta bor oldi bosh",
    "🏘 Boysun ➡️ Samarqandga chiqamiz 📦 pochta olamiz manzil bor",
    "➡️ Sheroboddan Toshkentga ketamiz 📦 pochta ham olamiz 🏘 Angor orqali",
    "🏘 Muzrabod ➡️ Samarqandga ketamiz 📦 pochta oldi bosh joy bor",
]
PASSENGER_ADS = [
    "Toshkentga taksi kerak 2 kishi iltimos",
    "Samarqandga mashina kerak bitta odam",
    "taksi kerak Buxoroga tezroq iltimos",
    "Denovga taksi kerak 1 kishi narxi qancha",
    "mashina kerak Navoiyga bitta joy",
]


def test_tokens_emoji_and_words(fresh):
    toks = learn._tokens("🏘 Termizdan 📦 pochta")
    assert "e:🏘" in toks and "e:📦" in toks
    assert "w:pochta" in toks and "w:termizdan" in toks
    assert "e:️" not in toks                       # variatsiya selektori (U+FE0F) belgida emas


def test_learn_then_guess_driver(fresh):
    for ad in DRIVER_ADS:
        learn.learn(ad, "driver")
    for ad in PASSENGER_ADS:
        learn.learn(ad, "passenger")
    # yangi, noaniq e'lon — lekin haydovchi belgilari (🏘 📦 ➡️ pochta/ketamiz) bilan
    assert learn.guess("🏘 Jarqurgon ➡️ Toshkentga ketamiz 📦 pochta olamiz") == "driver"
    # sof yo'lovchi xabari — haydovchi deb aytmaydi
    assert learn.guess("Qarshiga taksi kerak 1 kishi") is None
    # belgilar yetarli emas
    assert learn.guess("salom qalaysiz") is None


def test_guess_needs_minimum_counts(fresh):
    learn.learn("🏘 Termizdan 📦 pochta ketamiz", "driver")   # faqat bir marta ko'rildi
    assert learn.guess("🏘 Termizdan 📦 pochta ketamiz") is None


def test_passenger_marker_blocks_driver(fresh):
    for ad in DRIVER_ADS:
        learn.learn(ad, "driver")
    for _ in range(6):
        learn.learn("taksi kerak iltimos mashina", "passenger")
    # kuchli yo'lovchi markeri (taksi/kerak) bo'lsa — haydovchi demaydi
    assert learn.guess("🏘 📦 ➡️ ketamiz pochta taksi kerak") is None


def test_save_and_reload(fresh):
    for ad in DRIVER_ADS:
        learn.learn(ad, "driver")
    learn.save()
    learn.reset()                                   # xotiradan tozalaymiz -> fayldan qayta o'qiladi
    assert learn._load()["driver"].get("e:🏘", 0) >= 3


def test_corrupt_file_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / "learned.json"
    f.write_text("{buzuq", encoding="utf-8")
    monkeypatch.setattr(config, "LEARN_FILE", f)
    learn.reset()
    assert learn.guess("🏘 📦 ketamiz") is None      # yiqilmaydi
    learn.reset()


# ---------- AI backend fallback ----------
def test_ai_backends_single(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "k1")
    monkeypatch.setattr(config, "AI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(config, "AI_MODEL", "llama-3.1-8b-instant,llama-3.3-70b-versatile")
    monkeypatch.delenv("AI_API_KEY_2", raising=False)
    b = config.ai_backends()
    assert b == [("https://api.groq.com/openai/v1", "k1", "llama-3.1-8b-instant"),
                 ("https://api.groq.com/openai/v1", "k1", "llama-3.3-70b-versatile")]


def test_ai_backends_second_provider(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "k1")
    monkeypatch.setattr(config, "AI_BASE_URL", config.GROQ_BASE)
    monkeypatch.setattr(config, "AI_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setenv("AI_API_KEY_2", "k2")
    monkeypatch.setenv("AI_BASE_URL_2", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("AI_MODEL_2", "x-model:free")
    b = config.ai_backends()
    assert b[0] == (config.GROQ_BASE, "k1", "llama-3.1-8b-instant")
    assert ("https://openrouter.ai/api/v1", "k2", "x-model:free") in b


def test_ai_backends_empty_without_key(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    monkeypatch.delenv("AI_API_KEY_2", raising=False)
    assert config.ai_backends() == []
