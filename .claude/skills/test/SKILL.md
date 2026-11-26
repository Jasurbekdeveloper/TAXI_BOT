---
name: test
description: Taksi botning to'liq test to'plamini (pytest birlik testlari + soxta-Telegram e2e) to'g'ri muhit o'zgaruvchilari bilan yurgizadi. Kod o'zgargach yoki "testlarni yurgiz / tekshir" deyilganda ishlat.
---

# Taksi bot: testlarni yurgizish

Bu loyihada ikki xil test bor. Ikkalasini ham yurgizing va ikkalasi ham yashil bo'lishi shart.

## 1. Birlik testlar (pytest)
```bash
.venv/Scripts/python -m pytest -q tests
```

## 2. Soxta-Telegram e2e (real Telegramga ulanmaydi)
**Muhim:** Windows konsoli cp1251 bo'lgani uchun emoji chop etilganda `UnicodeEncodeError` beradi. Shuning uchun **har doim** UTF-8 o'zgaruvchilari bilan yurgizing:
```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python tests/e2e_fake_telegram.py
```

## Qoidalar
- Kodni o'zgartirgach, **ikkala** to'plamni ham yurgizing.
- Yangi xulq-atvor (NLP qoidasi, spam patterni, donor oqimi) qo'shsangiz — unga **test ham yozing** (`tests/test_nlp.py`, `tests/test_donor.py`, yoki `tests/e2e_fake_telegram.py`).
- Natijani rost ayting: test yiqilsa, chiqishi bilan birga ayting; o'tgan bo'lsa, nechta o'tganini yozing.
- Faqat bitta faylni tez tekshirish: `.venv/Scripts/python -m pytest -q tests/test_nlp.py`.

## Muhit eslatmalari
- Windows + Git Bash. Bash heredoc apostrofli matnni buzadi — fayllarni Write bilan yozing.
- Virtual muhit: `.venv/Scripts/python` (Windows yo'li).
