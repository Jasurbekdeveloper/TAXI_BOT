# Serverga qo'yish (Ubuntu VM, masalan Oracle Cloud Always Free)

Bu yo'riqnoma botni serverда 24/7 ishlaydiган qilib o'rnatadi. Buyruqlarni serverда (SSH orqali) bajaring.

## 0. Server
- **Oracle Cloud Always Free** (tavsiya): cloud.oracle.com → ro'yxatdan o'ting → **Compute → Instances → Create** → **Ubuntu 22.04** → Always Free shakli (`VM.Standard.A1` yoki `E2.1.Micro`). SSH kalitни saqlang.
- SSH bilan kiring: `ssh ubuntu@<SERVER_IP>`

## 1. Kerakli dasturlar
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
```

## 2. Kodni olish
```bash
cd ~
git clone https://github.com/Jasurbekdeveloper/TAXI_BOT.git
cd TAXI_BOT
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. .env yaratish (MAXFIY — serverda yoziladi, GitHubda yo'q)
```bash
nano .env
```
Quyidagilarni yozing (o'z qiymatlaringiz bilan):
```
MODE=both
BOT_TOKEN=<@BotFather tokeni>
DRIVERS_CHAT_ID=<maxfiy haydovchilar guruhi id>
ADMIN_IDS=<o'z Telegram ID'ingiz>
API_ID=<my.telegram.org>
API_HASH=<my.telegram.org>
AI_API_KEY=<console.groq.com kaliti>
```
(Agar userbot kerak bo'lmasa: `MODE=bot` qiling, API_ID/API_HASH shart emas.)
Saqlash: Ctrl+O, Enter, Ctrl+X.

## 4. Userbot login (faqat MODE=both bo'lsa, bir marta)
```bash
.venv/bin/python login_userbot.py
```
Telefon → Telegram ilovasidagi "Telegram" chatidan kelgan kod → (2FA bo'lsa parol).
Oxirida akkaunt guruhlari ro'yxati chiqadi.

## 5. Sinab ko'rish (bir marta qo'lda)
```bash
.venv/bin/python main.py
```
Log'da "Bot: @... | Rejim: both" va "Userbot ishga tushdi" chiqsa — ishlayapti. To'xtatish: Ctrl+C.

## 6. 24/7 ishlashi uchun systemd xizmati
```bash
sudo cp deploy/taxibot.service /etc/systemd/system/taxibot.service
sudo systemctl daemon-reload
sudo systemctl enable --now taxibot
```
Holatini ko'rish / log:
```bash
systemctl status taxibot
journalctl -u taxibot -f
```
Endi SSH yopilsa ham, server o'chib yonsa ham bot o'zi ishlab turadi.

## 7. Yangilanish (kod o'zgarса)
```bash
cd ~/TAXI_BOT
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart taxibot
```

## Eslatmalar
- `.env` va `*.session` fayllarni hech kimga bermang, GitHubga qo'ymang (ular `.gitignore`da).
- Userbot akkaunt **alohida raqam** bo'lsin (bloklanish xavfi).
- Botni bir vaqtda faqat **bitta** joyda ishlating (serverda ishlатsangiz, kompyuterда to'xtating).
- Serverda TLS/sertifikat muammosi bo'lmaydi — `USE_SYSTEM_CA` kerak emas.
