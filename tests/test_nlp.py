import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nlp

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
