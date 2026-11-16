"""AI tasniflash qarori (pipeline.decide) va haydovchi e'lonini formatlash (services/ad_format)."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai
import config
import nlp
import pipeline
from services import ad_format


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []
    answers = {}

    async def classify(text):
        calls.append(text)
        return answers.get(text)
    monkeypatch.setattr(config, "AI_API_KEY", "x")
    monkeypatch.setattr(config, "AI_MIN_CONFIDENCE", 0.6)
    monkeypatch.setattr(ai, "classify", classify)
    return calls, answers


def decide(text):
    return asyncio.run(pipeline.decide(text, nlp.analyze(text)))[:2]


def res(label, conf):
    return {"label": label, "confidence": conf, "from": None, "to": None, "seats": None, "time": None}


def test_clear_cases_skip_ai(fake_ai):
    calls, _ = fake_ai
    assert decide("Toshkentdan Samarqandga taksi kerak 2 kishi") == ("passenger", "kw")
    assert decide("Toshkentga ketaman, kim bor? 4 joy bosh") == ("driver", "kw")
    assert decide("Salom hammaga") == ("unknown", "kw")
    assert calls == []                                      # aniq xabarlar va gap-so'zlar AI'ga bormaydi


def test_suspicious_passenger_verified_by_ai(fake_ai):
    calls, answers = fake_ai
    t = "Toshkentga taksi kerak Cobalt"                     # yo'lovchi, lekin mashina nomi (haydovchi belgisi) bor
    answers[t] = res("driver", 0.9)
    assert decide(t) == ("driver", "ai") and calls == [t]   # AI ishonch bilan tuzatdi
    answers[t] = res("driver", 0.4)
    assert decide(t) == ("passenger", "ai")                 # ishonch past: kalit so'z natijasi qoladi


def test_unknown_needs_confident_ai(fake_ai):
    _, answers = fake_ai
    t = "Toshkent yaqinmi"
    answers[t] = res("passenger", 0.5)
    assert decide(t) == ("unknown", "ai")                   # ishonchsiz AI natijasi qabul qilinmaydi
    answers[t] = res("passenger", 0.8)
    assert decide(t) == ("passenger", "ai")


def test_ai_failure_keeps_keywords(fake_ai):
    assert decide("Toshkentga taksi kerak Cobalt") == ("passenger", "kw")   # AI javob bermadi


DRIVER_AD = ("SURXONDARYODAN TOSHKENTGA KETAMIZ ERTAGA TERMIZ ANGOR MUZRABOTDAN 3 TA JOY BOR OLDI BOʻSH "
             "AYOL YOʻLAVCHI BOR TEL +998975990820 TEL +998880534468")


def test_ad_format_full():
    text, info = asyncio.run(ad_format.build(DRIVER_AD, use_ai=False))
    assert text == ("🚕 SURXONDARYO ➜ TOSHKENT\n📍 Termiz · Angor · Muzrabot orqali\n🗓 Ertaga\n💺 3 ta bo'sh joy\n"
                    "✅ Oldi o'rindiq bo'sh\n👩 Ayol yo'lovchi bor\n📞 +998 97 599 08 20\n📞 +998 88 053 44 68")


def test_ad_format_extras_and_cyrillic():
    text, _ = asyncio.run(ad_format.build(
        "Тошкентдан Термизга бугун 18:30 да чиқамиз Кобалт кондиционер бор 2 жой 250 минг почта оламиз 901112233",
        use_ai=False))
    for part in ("🚕 TOSHKENT ➜ TERMIZ", "🕕 Bugun 18:30", "💺 2 ta bo'sh joy", "🚗 Cobalt", "📦 Pochta",
                 "💰 250 ming", "📞 +998 90 111 22 33"):
        assert part in text, (part, text)


def test_ad_format_ai_fills_gaps(monkeypatch):
    async def extract_ad(t):
        return {"from": "Denov", "to": "Toshkent", "stops": ["Sho'rchi"], "time": None, "seats": 2, "car": None,
                "price": None, "phones": ["+998 93 000 00 01"], "pochta": True, "ayol": False, "oldi_bosh": False,
                "konditsioner": False, "bagaj": False}
    monkeypatch.setattr(ai, "extract_ad", extract_ad)
    text, info = asyncio.run(ad_format.build("Toshkentga ketamiz 2 joy"))
    assert info.frm == "Denov" and info.to == "Toshkent" and "📦 Pochta ham olamiz" in text
    assert "📞 +998 93 000 00 01" in text


def test_ad_format_not_enough():
    assert asyncio.run(ad_format.build("Salom, qalaysizlar", use_ai=False))[0] is None
