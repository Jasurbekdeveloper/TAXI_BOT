---
name: deploy
description: Taksi botni Oracle Cloud serveriga (systemd `taxibot` xizmati) chiqarish bo'yicha qadamlar va tekshiruvlar. "Deploy / serverga chiqar / yangila" deyilganda yoki o'zgarishdan keyin serverni yangilash kerak bo'lganda ishlat.
---

# Taksi bot: serverga deploy

Bot Oracle Cloud Ubuntu serverida `systemd` xizmati sifatida ishlaydi (xizmat nomi: `taxibot`).
Repo: github.com/Jasurbekdeveloper/TAXI_BOT, `main` tarmog'i. Deploy foydalanuvchi tomonidan serverda bajariladi — unga aniq buyruqlarni bering.

## Deploydan oldin (shu kompyuterда)
1. Testlarni yurgizing (`test` skilli) — ikkalasi ham yashil bo'lsin.
2. O'zgarishni commit qiling va `git push` qiling.
3. Commit xabari oxiriga attribution qatorini qo'ying (agar talab qilinsa).

## Serverда (foydalanuvchi bajaradi)
```bash
cd ~/TAXI_BOT && git pull && sudo systemctl restart taxibot
```

Tekshirish:
```bash
sudo systemctl status taxibot
```
`active (running)` (yashil) bo'lsa — ishlayapti. Qaysi versiya ishlayotganini tasdiqlash:
```bash
cd ~/TAXI_BOT && git log --oneline -1
```

## Loglarni ko'rish (diagnostika)
```bash
sudo journalctl -u taxibot --since "15 min ago" --no-pager
```
Donor kontakt diagnostikasi:
```bash
sudo journalctl -u taxibot --since "15 min ago" --no-pager | grep -E "\[donor\] kontakt|username aniqlanmadi"
```

## Keng tarqalgan muammolar
- **`git pull` da "local changes" xatosi** (odatda `.env` tufayli): `.env` hech qachon repoda bo'lmasligi kerak. Agar serverda qo'lda tahrirlangan bo'lsa — `git stash` qiling, `git pull`, keyin kerak bo'lsa `.env` ni qayta sozlang. `.env`, token, `*.session`, `fernet.key`, `taxi.db` ni **hech qachon** chatga chiqarmang.
- **Bir token = bir nusxa:** ayni vaqtda bitta BOT_TOKEN bilan faqat bitta nusxa ishlashi kerak (serverda va lokalда bir vaqtda ishga tushirmang).
- **TLS ushlanishi** (`CERTIFICATE_VERIFY_FAILED`): SSL tekshiruvini o'chirmang — `.env` da `USE_SYSTEM_CA=1` qiling.
- **Eski jarayon loglari:** loglarni o'qiganда PID ni tekshiring. Qayta ishga tushirishdan **oldingi** PID loglari eski kodni ko'rsatadi — yangi xulqni tasdiqlash uchun qayta ishga tushirgandan **keyingi** loglarga qarang.
