import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nlp


def test_driver_kishi_kerak_and_typos():
    # "N kishi kerak" = haydovchi yo'lovchi qidiryapti (maxfiy guruhga tushmasligi kerak), imlo xatolari bilan
    assert nlp.analyze("Oltinsoy dinov shurchdan toshkinga kitamz 1 kishi kirak 959827797").label == "driver"
    assert nlp.analyze("Denovdan Toshkentga 3 kishi kerak").label == "driver"
    # "taksi kerak" esa yo'lovchi (imlo bilan ham)
    assert nlp.analyze("taksi kirak Toshkentga").label == "passenger"
    # imlo normalizatsiyasi
    assert "kerak" in nlp.normalize("1 kishi kirak")
    assert "ketamiz" in nlp.normalize("toshkinga kitamz")


def test_tidy_strips_branding_phone_emoji():
    # imzo/reklama qatori, hashtag, @mention, telefon, emoji devori — tozalanadi
    raw = ("‼️‼️‼️‼️ Denovdan Toshkentga 1 odam bor\nTel: +998901234567\n"
           "Сафар Такси\n#Denov_Toshkent @reklama_kanal")
    out = nlp.tidy(raw)
    assert "Denovdan Toshkentga 1 odam bor" in out
    assert "998901234567" not in out and "Tel" not in out        # telefon alohida ko'rsatiladi
    assert "Сафар Такси" not in out and "#Denov" not in out and "@reklama" not in out
    assert "‼️‼️" not in out                                       # emoji devori olib tashlandi


def test_tidy_keeps_phone_when_asked():
    assert "90 123 45 67" in nlp.tidy("Toshkentga odam bor 90 123 45 67", drop_phones=False)


def test_is_spam():
    assert nlp.is_spam("Feyk xabar")
    assert nlp.is_spam("Sizga taksi keràkmi unda bot ustiga bosing")
    assert nlp.is_spam("Yangi xabar matnini kiriting")
    assert nlp.is_spam("🔥🔥🔥")                                  # mazmunli harf yo'q
    assert not nlp.is_spam("Denovdan Toshkentga taksi kerak 2 kishi")
    assert not nlp.is_spam("Toshkentga odam bor")


def test_fmt_phone():
    assert nlp.fmt_phone("998901234567") == "+998 90 123 45 67"       # profil raqami (plyussiz)
    assert nlp.fmt_phone("+998 90 123 45 67") == "+998 90 123 45 67"
    assert nlp.fmt_phone("901234567") == "+998 90 123 45 67"          # 9 xonali -> 998 qo'shiladi
    assert nlp.fmt_phone(None) is None
    assert nlp.fmt_phone("12345") is None                              # noto'g'ri
    assert nlp.fmt_phone("79161234567") is None                        # O'zbek raqami emas

CASES = [
    # matn, label, frm, to, seats, when
    ("Toshkentdan Samarqandga taksi kerak 2 kishi +998901234567", "passenger", "Toshkent", "Samarqand", 2, None),
    ("Тошкентдан Самарқандга мошина керак 3 киши", "passenger", "Toshkent", "Samarqand", 3, None),
    ("Нужно такси из Ташкента в Самарканд", "passenger", "Toshkent", "Samarqand", None, None),
    ("В Самарканд из Ташкента нужно такси", "passenger", "Toshkent", "Samarqand", None, None),
    ("Samarqandga ketaman 1 kishi", "passenger", None, "Samarqand", 1, None),
    ("Toshkentga mashina bormi?", "passenger", None, "Toshkent", None, None),
    ("Andijonga taksi bormi", "passenger", None, "Andijon", None, None),
    ("Joy bormi Buxoroga?", "passenger", None, "Buxoro", None, None),
    ("Moshin kerak Namanganga", "passenger", None, "Namangan", None, None),
    ("Ikki kishi Toshkentga ketish kerak", "passenger", None, "Toshkent", 2, None),
    ("Toshkentga mashina kerak soat 14:00da", "passenger", None, "Toshkent", None, "14:00"),
    ("Samarqandga taksi kerak 18:30ga", "passenger", None, "Samarqand", None, "18:30"),
    ("Samarqandga taksi kerak soat 8 da", "passenger", None, "Samarqand", None, "08:00"),
    ("Ertaga ertalab Buxoroga taksi kerak", "passenger", None, "Buxoro", None, "ertaga ertalab"),
    ("Buxoroga taksi kerak 12.11.2026 kuni", "passenger", None, "Buxoro", None, None),
    ("Toshkentga pochta bor, kim olib ketadi", "passenger", None, "Toshkent", None, None),
    ("Toshga ketish kerak", "passenger", None, "Toshkent", None, None),
    ("Taksi kerak emas, rahmat", "unknown", None, None, None, None),
    ("Mashina kerakmi? Toshkentga ketyapman", "driver", None, "Toshkent", None, None),
    ("Toshkentga odam bormi?", "driver", None, "Toshkent", None, None),
    ("Samarqandga pochta bormi?", "driver", None, "Samarqand", None, None),
    ("Toshkentga ketyapman, Cobalt, 3 joy bor", "driver", None, "Toshkent", 3, None),
    ("Еду в Ташкент, есть места", "driver", None, "Toshkent", None, None),
    ("Pochtani tashlab keting, Samarqandga taksi kerak", "passenger", None, "Samarqand", None, None),
    ("Yukni tashlash kerak Buxoroga taksi kerak", "passenger", None, "Buxoro", None, None),
    ("Qarshilik yoq, Andijonga taksi kerak", "passenger", None, "Andijon", None, None),
    ("Salom hammaga", "unknown", None, None, None, None),
    ("Surxondaryodan Toshkentga taksi kerak", "passenger", "Surxondaryo", "Toshkent", None, None),
    ("Шўрчидан Тошкентга мошина керак 2 киши", "passenger", "Sho'rchi", "Toshkent", 2, None),
    ("Toshdan Denovga ketaman", "passenger", "Toshkent", "Denov", None, None),
    # haydovchi e'lonlari maxfiy guruhga tushmasligi kerak
    ("Hozir Toshkentga ketaman, kim bor?", "driver", None, "Toshkent", None, "hozir"),
    ("Pochta olib ketaman Toshkentga", "driver", None, "Toshkent", None, None),
    ("Toshkentga boraman, kimga kerak", "driver", None, "Toshkent", None, None),
    ("Termizdan Toshkentga boraman, odam olaman", "driver", "Termiz", "Toshkent", None, None),
    ("Assalomu alaykum Toshkentga ketaman yoʻlovchi kerak", "driver", None, "Toshkent", None, None),
    ("Toshkentga ketaman 4 joy bosh", "driver", None, "Toshkent", 4, None),
    ("Toshkentga ketaman bugun, 2 kishi bor joy", "driver", None, "Toshkent", 2, "bugun"),
    ("Сурхондарёдан Тошкент кетамиз 2⃣киши керак Термиз Ангор Шеработдан 👠 айол киши бор 📦 Почта хам оламиз",
     "driver", "Surxondaryo", "Toshkent", 2, None),
    ("SURXONDARYODAN TOSHKENTGA KETAMIZ ERTAGA MUZRABOTDAN 3 TA JOY BOR OLDI BOʻSH AYOL YOʻLAVCHI BOR",
     "driver", "Surxondaryo", "Toshkent", 3, "ertaga"),
    ("Toshkentdan Termizga ketamiz, oldi bo'sh, yo'lga chiqamiz", "driver", "Toshkent", "Termiz", None, None),
    ("Jarqoʻrgʻondan Quqonga powta bor", "passenger", "Jarqo'rg'on", "Qo'qon", None, None),
    ("Qumqurgondan Toshkentga taksi kerak", "passenger", "Qumqo'rg'on", "Toshkent", None, None),
    # tez/xato yozilgan haydovchi e'lonlari
    ("Ertaga ertalab \nToshkentga ketamz \nodam poshta olamz\n+998998269111", "driver", None, "Toshkent", None,
     "ertaga ertalab"),
    ("Toshkentga ketvomiz 2 odam olamz", "driver", None, "Toshkent", 2, None),
    ("Termizga ketyabmiz pochta olamz", "driver", None, "Termiz", None, None),
    ("Samarqandga ketamz, 2 kishimiz, mashina kerak", "passenger", None, "Samarqand", 2, None),
    ("Pochta bor Toshkentga kim olib ketadi", "passenger", None, "Toshkent", None, None),
]


@pytest.mark.parametrize("text,label,frm,to,seats,when", CASES)
def test_analyze(text, label, frm, to, seats, when):
    p = nlp.analyze(text)
    assert (p.label, p.frm, p.to, p.seats, p.when) == (label, frm, to, seats, when)


@pytest.mark.parametrize("raw,want", [
    ("90 123 45 67", "+998 90 123 45 67"),
    ("+998 (90) 123-45-67", "+998 90 123 45 67"),
    ("901234567", "+998 90 123 45 67"),
    ("998901234567", "+998 90 123 45 67"),
    ("12345678901234", None),
])
def test_phone(raw, want):
    assert nlp.find_phone(raw) == want


def test_small_talk_skips_ai():
    assert not nlp.worth_ai("Salom hammaga", nlp.analyze("Salom hammaga"))
    assert nlp.worth_ai("Toshkent yaqinmi", nlp.analyze("Toshkent yaqinmi"))


def test_w_instead_of_sh_driver():
    p = nlp.analyze("TERMEZDAN TOWKENTGA 1️⃣ KIWI KERAK POWTA XAM OLAMIZ +998994699500")
    assert p.label == "driver"
    assert (p.frm, p.to) == ("Termiz", "Toshkent")


def test_broadcast_bot_signature_is_driver():
    p = nlp.analyze("Samarqanddan Toshkentga ketamiz\n@avtoxabarchi02bot orqali yuborildi")
    assert p.label == "driver"


def test_w_passenger_still_passenger():
    p = nlp.analyze("Towkentdan Qarshiga 1 kiwi bor ketadigan bormi")
    assert p.label != "driver"


def test_driver_takes_people_and_mail():
    p = nlp.analyze("TOSHKENTDAN TERMEZ ANGOR Muzrabod Sherabodga Qaytaman Odam Va Po'chtalar Olaman "
                    "Tom Bagaj Bor +998996041116")
    assert p.label == "driver"
    assert p.frm == "Toshkent"


def test_kiwi_seats():
    assert nlp.analyze("Qarshiga 1kiwi bor ketadigan bormi").seats == 1
