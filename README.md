# Taksi guruhlari boti

Katta taksi guruhlaridagi **yo'lovchi** xabarlarini aniqlab, haydovchilar guruhiga chiroyli e'lon qilib yuboradi.

## O'rnatish
Python 3.10+ kerak.
```bash
pip install -r requirements.txt
cp .env.example .env      # qiymatlarni to'ldiring
python main.py
```

## Birinchi sozlash
1. @BotFather → `/setprivacy` → botni tanlang → **Disable**. Bu bo'lmasa bot guruh xabarlarini ko'rmaydi.
2. Botni haydovchilar guruhiga qo'shing va u yerda `/id` yozing. Chiqqan raqamni `.env` dagi `DRIVERS_CHAT_ID` ga yozing.
3. Botni qayta ishga tushiring. Startda log'da muammolar aniq yoziladi.
4. Quyidagi usullardan biri bilan kuzatiladigan guruhlarni qo'shing.

> Privacy o'zgartirilgandan keyin bot oldin qo'shilgan guruhlardan chiqarilib, qayta qo'shilishi kerak.

## Bot orqali taksi buyurtma qilish
Yo'lovchi botga shaxsiy yozadi (`/start` yoki `/order`). Bot ketma-ket so'raydi: qayerdan, qayerga, qachon, telefon.
Yo'lovchi tasdiqlagach, buyurtma haydovchilar guruhiga «✅ Oldim» tugmasi bilan boradi.
Haydovchi bossa, yo'lovchiga kim olgani yoziladi va haydovchi telefon yoki bot orqali bog'lanadi.

- Birdan `Toshkentdan Denovga ertaga 18:30` deb yozilsa, shu ma'lumotlar qayta so'ralmaydi.
- `/cancel` — bekor qilish. Ikki buyurtma orasida `ORDER_COOLDOWN_SEC` (120 s) kutiladi.
- To'ldirilayotgan buyurtma xotirada turadi, restartda yo'qoladi. Telefon raqamlari diskka yozilmaydi.
- `OFFER_IN_GROUPS=1` qilinsa, manba guruhlarda yo'lovchi xabariga botga o'tish tugmasi bilan javob beriladi (bir odamga kuniga 1 marta). Guruh egalari reklama deb bilishi mumkin, shuning uchun standart holatda o'chiq.

## Haydovchi yo'lovchiga qanday yozadi
- **«💬 Yozish» tugmasi:** username bo'lsa `t.me/username`, bo'lmasa `tg://user`. Yo'lovchining maxfiylik sozlamasi taqiqlasa, e'lon tugmasiz chiqadi.
- **Bot orqali yozishuv** (faqat bot orqali berilgan buyurtmalar): «Oldim» bosilgach, haydovchi botga yozgani yo'lovchiga boradi, javobi qaytib keladi. Matn, rasm, ovoz va joylashuv o'tadi, forward qilinmagani uchun profil ko'rinmaydi. Haydovchining raqami yo'lovchiga ko'rinmaydi.
- Haydovchi botni hali ochmagan bo'lsa, «Oldim» botni o'zi ochadi yoki e'londagi «💬 Bot orqali yozish» tugmasini bosadi.
- `/chats` — ochiq suhbatlar va ular orasida almashish, `/end` — yakunlash. Suhbat 24 soat jim tursa yoki bot qayta ishga tushsa, yopiladi.
- Guruhdan topilgan yo'lovchiga bot birinchi bo'lib yoza olmaydi. Uning uchun faqat telefon, username, tugma va asl xabarga havola qoladi.

## Manba guruh/kanallarni boshqarish
Manbalar `.env` da emas, `groups.json` da saqlanadi (restartdan keyin ham qoladi). Guruh ham, **kanal** ham qo'shiladi.

**Eng oson — tugmali panel: `/menu`** (admin, shaxsiy chatda). U yerda:
- **➕ Guruhga qo'shish / ➕ Kanalga qo'shish** — bosilganda Telegram botni siz tanlagan joyga qo'shadi.
- **🔗 Havola / forward bilan qo'shish** — @username, t.me havola yoki IDni yuborasiz, yoki o'sha guruh/kanaldagi xabarni shu botga forward qilasiz.
- **📋 Ro'yxat** — ❌ tugmalar bilan o'chirish.
- **👤 Userbot holati** — user sifatida o'qishni yoqish bo'yicha ko'rsatma.

Slash buyruqlar ham ishlaydi (zaxira sifatida):

| Amal | Qanday |
|---|---|
| Botni guruh/kanalga qo'shish | Admin qo'shsa, **avtomatik** kuzatuvga olinadi (kanalda bot admin bo'lsin) |
| Guruh ichidan | `/add` |
| Istalgan joydan | `/addgroup @guruh @kanal t.me/guruh2 -100123` |
| O'chirish | `/delgroup @guruh` yoki `/groups` dagi ❌ tugma |
| Ro'yxat | `/groups` |

- **Kanallar:** bot kanal postlarini faqat **admin** bo'lsa o'qiydi. Begona (o'zingizники bo'lmagan) kanallarni o'qish uchun userbot kerak (quyida).
- **Admin** — haydovchilar guruhining egasi va adminlari (avtomatik). Qo'shimcha: `.env` dagi `ADMIN_IDS`.
- Begona odam botni o'z guruhi/kanaliga qo'shsa, u kuzatilmaydi: haydovchilar guruhiga tasdiqlash tugmasi chiqadi, faqat admin bosa oladi.
- `MODE=bot` da bot guruh/kanalga a'zo (kanalda admin) bo'lishi kerak. `userbot`/`both` rejimida akkaunt obuna bo'lgan guruh va kanallarni bot ichida bo'lmasa ham o'qiydi. Yopiq taklif havolalari qo'llab-quvvatlanmaydi.

## Guruh moderatsiyasi
Botni istalgan guruhga qo'shib, **admin** qiling. Unga «Xabarlarni o'chirish» va «Foydalanuvchilarni bloklash» huquqlari kerak. Bot quyidagilarni qiladi:
- kirdi-chiqdi xabarlarini o'chiradi;
- reklamani o'chiradi: havola, begona @kanal, kanaldan forward, kanal nomidan yozilgan xabar, havolali tugma va spam so'zlar. Odamning o'z @username'i mumkin;
- flood qilganni 5 daqiqaga cheklaydi.

Guruh adminlarining xabarlariga tegmaydi. Guruh ichida `/settings` yozilsa, har bir funksiyani yoqib-o'chirish tugmalari va o'chirilgan xabarlar soni chiqadi. Bu buyruq faqat guruh adminlari uchun. Sozlamalar `moderation.json` da saqlanadi.

## AI (noaniq xabarlar)
`.env` da `AI_API_KEY` bo'sh bo'lsa, faqat kalit so'z bilan aniq tanilgan e'lonlar o'tadi, noaniqlari tashlanadi. Groq kaliti qo'ysangiz (bepul: console.groq.com → API Keys), bot noaniq xabarlarni ham AI bilan tasniflaydi. Kalit `AI_API_KEY` ga yoziladi, model `AI_MODEL` (default `openai/gpt-oss-20b`).

## Rol tanlash
`/start` da foydalanuvchi **yo'lovchi** yoki **haydovchi** ekanini tanlaydi. Yo'lovchi → buyurtma oqimi. Haydovchi → qisqa ma'lumot (e'lonlar maxfiy guruhda chiqadi). Rol `users.json` da saqlanadi.

## Yo'nalish filtri va hashtag
`/menu` → **🧭 Yo'nalishlar** da xizmat qilinadigan yo'nalishlarni qo'shasiz (masalan Termiz–Toshkent). Shundan keyin maxfiy guruhga **faqat** o'sha yo'nalishdagi e'lonlar tushadi. Ro'yxat bo'sh bo'lsa, hammasi o'tadi. Yo'nalishi aniqlanmagan e'lonlar standart holatda o'tkaziladi (`ROUTE_FILTER_STRICT=0`).

Har e'longa yo'nalish **hashtagi** qo'shiladi (`#Toshkent_Termiz`). Maxfiy guruhda shu hashtagni bosib, faqat kerakli yo'nalishdagi e'lonlarni filtrlab ko'rasiz.

## Agregator / tarqatkich (userbot) — `/agregator`
Bitta userbot akkaunt bir nechta taksi guruhiga a'zo bo'lib, bir vaqtda: o'sha guruhlarга "yo'lovchi izlayman" e'lonini **jadval bo'yicha** tarqatadi va o'sha guruhlardan yo'lovchi e'lonlarini maxfiy guruhga yig'adi.

Tugmalar (faqat admin): **👥 Guruhlar** (akkaunt guruhlaridan faollarini tanlash), **✍️ E'lon matni**, **⏸ To'xtatish**, **📊 Hisobot** (oxirgi 24 soat, har guruhda nechta), **❓ Yordam**, **❌ Akkauntni uzish**.

Ishlashi uchun userbot kerak:
1. **Alohida telefon raqam** (asosiy emas — bloklanish xavfi).
2. my.telegram.org → **API development tools** → `API_ID`, `API_HASH` → `.env`.
3. `.env`: `MODE=both`, `API_ID`, `API_HASH`. Birinchi ishga tushirishda terminalda telefon + Telegram kodi bilan login (keyin `.session` saqlanadi).
4. Akkaunt o'sha guruhlarga a'zo bo'lishi shart.

⚠️ Akkauntni bot kabi ishlatish Telegram qoidalariga ziddir; tez-tez yuborish bloklaydi. Minimal oraliq `BROADCAST_MIN_INTERVAL_MIN` (30 daq), kunlik limit `BROADCAST_MAX_PER_DAY`. "Akkauntni uzish" sessiyani o'chiradi; bot qayta ishga tushganda `MODE=bot` qiling.

## Rejimlar (`MODE`)
| Rejim | Qanday ishlaydi | Talab |
|---|---|---|
| `bot` | Bot manba guruhlarga a'zo, xabarlarni o'zi o'qiydi | BotFather → `/setprivacy` → **Disable**, keyin botni guruhga qayta qo'shish |
| `userbot` | Oddiy akkaunt (Telethon) begona guruhlarni o'qiydi, bot faqat haydovchilar guruhiga yozadi | `API_ID`, `API_HASH` (my.telegram.org). Birinchi ishga tushirishda telefon va kod so'raladi |
| `both` | Ikkalasi birga | — |

Har ikki rejimda ham bot **haydovchilar guruhiga a'zo** bo'lishi kerak (admin shart emas).

## Xabar qanday tushuniladi
1. **Kalit so'zlar** (`nlp.py`): lotin, kirill va ruscha matn normalizatsiya qilinadi, so'zlarga ball beriladi.
2. **AI** (`ai.py`): noaniq, lekin taksiga aloqasi bor xabarlar bepul OpenAI-mos API'ga yuboriladi (default: Groq). `AI_API_KEY` bo'sh bo'lsa, AI ishlatilmaydi va noaniq xabarlar e'lon qilinmaydi.

Ajratiladigan ma'lumot: qayerdan → qayerga, vaqt, kishi soni, telefon.

## Qo'shimcha imkoniyatlar
- **Dedup:** bir odam bir xabarni ko'p guruhga tashlasa, 45 daqiqa ichida faqat bitta e'lon chiqadi. Yetkazilmagan e'lon dublikat sanalmaydi.
- **Navbat:** Telegram limitidan oshmaslik uchun ~18 xabar/daqiqa. Tarmoq xatosida 3 martagacha qayta yuboriladi.
- **Eski xabarlar:** bot o'chiq turganda to'plangan, `MAX_AGE_MINUTES` (15 daqiqa) dan eski xabarlar e'lon qilinmaydi.
- **«✅ Oldim» tugmasi:** birinchi bosgan haydovchi oladi, qolganlarga kim olgani ko'rsatiladi.
- **Buyruqlar:** `/order`, `/cancel` (yo'lovchi), `/chats`, `/end` (suhbat), `/id` (chat ID, hamma uchun), `/help`, `/stats` (faqat admin).

## Sozlash
- Yangi so'z yoki shahar qo'shish: `nlp.py` dagi `PASSENGER_KW`, `DRIVER_KW`, `CITIES`.
- Testlar: `pip install pytest`, keyin `python -m pytest tests`.
- Korporativ tarmoqda sertifikat xatosi (`CERTIFICATE_VERIFY_FAILED`) chiqsa: `USE_SYSTEM_CA=1`.
- ⚠️ Userbot rejimi Telegram qoidalariga zid bo'lishi mumkin. Asosiy akkauntingizni ishlatmang.
- ⚠️ `.env` va `*.session` fayllari maxfiy: session akkauntga to'liq kirish beradi. Ularni hech kimga bermang.
- Navbat, dedup va statistika xotirada turadi, restartda tozalanadi. Faqat guruhlar ro'yxati saqlanadi.
#   T A X I _ B O T  
 