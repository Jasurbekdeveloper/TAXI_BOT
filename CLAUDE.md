# Taksi boti: loyiha xulosasi

Foydalanuvchi bilan o'zbek tilida gaplashing. Bu fayl kodni qayta o'qimaslik uchun yozilgan: avval shunga tayaning, keyin faqat kerakli faylni oching. Holat 2026-11-17 uchun.

## Vazifasi
Taksi guruhlaridagi yo'lovchi xabarlarini aniqlab, haydovchilar guruhiga e'lon qiladi. Yo'lovchi botning o'zida ham buyurtma bera oladi. Bot: `@taksi_surxandaryo_tashkentbot`. Stack: Python 3.12, aiogram 3.31, Telethon, httpx, SQLite, cryptography (Fernet).

## Fayllar
| Fayl | Vazifa |
|---|---|
| `main.py` | Ishga tushirish, guruh xabarlari, «Oldim», userbot, preflight |
| `admin.py` | Guruh boshqaruvi, `is_admin`, `/stats`, `/id`, `/help`, botning guruhga qo'shilishi |
| `moderation.py` | Guruh moderatsiyasi: kirdi-chiqdi, reklama, flood, `/settings`, salom xabari. `moderation.json` |
| `panel.py` | Tugmali boshqaruv paneli `/menu`: guruh/kanal qo'shish, ro'yxat, **yo'nalishlar** (filtr), userbot holati (FSM) |
| `database/models.py` | SQLite sxemasi: `users` (obuna, blok), `user_sessions` (shifrlangan sessiya, e'lon, interval), `session_groups`, `post_log`, `routes` (yo'nalish + yopiq guruh), `bot_settings`. users.json/routes.json bir marta ko'chiriladi |
| `database/crud.py` | Bazaga barcha murojaatlar |
| `services/crypto.py` | Fernet: `SESSION_SECRET` yoki avtomatik `fernet.key` |
| `services/userbot_auth.py` | Haydovchi akkauntini bot ichida ulash: telefon → kod (`1 2 3 4 5`) → 2FA → StringSession shifrlanib saqlanadi |
| `services/ad_format.py` | Haydovchi e'lonini ajratadi (marshrut, oraliq shaharlar, vaqt, joy, mashina, narx, telefonlar, pochta/ayol/oldi bo'sh) va bir xil formatga keltiradi; AI bo'sh maydonlarni to'ldiradi |
| `services/broadcaster.py` | `manager`: ko'p sessiya. Har akkaunt tanlangan guruhlarini O'QIYDI (→ pipeline) va TARQATADI (fon vazifa, interval, anti-spam, FloodWait/forbidden/revoked) |
| `handlers/driver_cabinet.py` | Haydovchi kabineti (`/driver`, `role:driver`): ulash FSM, guruh tanlash (sahifalangan, `dc:*`), e'lon, interval 15/30/60, 🚀/🛑, hisobot, uzish |
| `handlers/admin_panel.py` | `/admin` (faqat `ADMIN_IDS`, `ap:*`): statistika, haydovchilar/obuna/blok/sessiya, yo'nalishlar→yopiq guruh, sozlamalar + Global Stop, umumiy xabarnoma |
| `handlers/middlewares.py` | `TrackUsers`: har shaxsiy xabarda foydalanuvchini bazaga yozadi, bloklanganni to'xtatadi |
| `userstore.py` | Foydalanuvchi roli — endi bazadagi `users` jadvaliga o'ram |
| `routes.py` | Yo'nalishlar (bazada). `allowed()`, `target_chat()` (Smart Routing), `closed_chat_ids()`, `parse_pair()` |
| `order.py` | Buyurtma oqimi (FSM), `offer_in_group` |
| `relay.py` | Haydovchi va yo'lovchi bot orqali yozishuvi |
| `pipeline.py` | Tahlil, AI, dedup, navbat, `render`, `_deliver` (tugma rad etilsa tugmasiz yuboradi) |
| `nlp.py` | Kalit so'zlar (`PASSENGER_KW`, `DRIVER_KW`), `CITIES`, marshrut, vaqt, telefon |
| `ai.py` | OpenAI-mos API (Groq). `classify()`: yangi prompt + 5 misol, `confidence`, 1 soatlik kesh, 429 da qayta urinish, mustahkam JSON. `extract_ad()`: haydovchi e'loni maydonlari |
| `store.py` | `groups.json` (kuzatiladigan guruhlar) |
| `config.py` | `.env`, `validate()` |
| `tests/` | `test_nlp.py`, `test_store.py`, `e2e_fake_telegram.py` (soxta Telegram+AI server) |

Routerlar tartibi muhim: `admin, admin_panel, moderation, panel, driver_cabinet, relay, order, main`. driver_cabinet reply-tugmalari order dagi erkin-matn handleridan oldin. Umumiy guruh handleri oxirida turishi shart.

## Funksiyalar
- **Kuzatish:** faqat `groups.json` dagi guruh/kanallar. Admin botni guruh/kanalga qo'shsa avtomatik. Begona qo'shsa, haydovchilar guruhiga «✅ Kuzatish» chiqadi. Har bir yozuvda `kind` ("group"/"channel").
- **Kanallar (2026-11-16):** bot kanalda **admin** bo'lsa, kanal postlarini o'qiydi (`channel_post`). Begona kanallar uchun userbot: akkaunt obuna bo'lsa, bot kanalda bo'lmasa ham o'qiydi (`is_channel`). Kanal postida shaxsiy muallif yo'q (user_* = None), e'lon manba havola bilan beriladi.
- **Tugmali panel (2026-11-16):** `/menu` (admin, shaxsiy chat). Tugmalar: «➕ Guruhga/Kanalga qo'shish» (Telegram deep-link `?startgroup`/`?startchannel`), «🔗 Havola/forward bilan qo'shish» (FSM: @username, t.me, ID yoki forward), «📋 Ro'yxat» (❌ tugmalar), «👤 Userbot holati». Slash buyruqlar zaxira. `add_watch()` — `/addgroup` va panel uchun umumiy.
- **Admin buyruqlari:** `/add` (guruh ichida), `/addgroup @a t.me/b -100123`, `/delgroup`, `/groups` (❌ tugma bilan), `/stats`, `/help`. `/id` hamma uchun.
- **Admin kim:** `ADMIN_IDS` yoki haydovchilar guruhi egasi/adminlari.
- **Tasniflash (2026-11-17):** kalit so'zlar → `pipeline.decide`. AI'ga boradi: (1) noaniq xabar, (2) «yo'lovchi» chiqqan-u haydovchi belgisi ham bor (tekshiruv). AI ishonchi ≥ `AI_MIN_CONFIDENCE` (0.6) bo'lsa qabul qilinadi, tekshiruvda boshqacha desa AI ustun (`stats.ai_overrides`). AI ishlamasa kalit so'z natijasi qoladi. `AI_API_KEY` bo'sh bo'lsa noaniq xabar tashlanadi. Log: `[label/kw|ai]`.
- **E'lon formatlash (2026-11-17):** kabinetda «✍️ E'lon matni» → `ad_format.build` → oldindan ko'rish: «✅ Shu ko'rinishda» / «📝 O'z matnim» / «✏️ Qayta yozish». Userbot e'lonni `parse_mode=None` bilan yuboradi.
- **E'lon:** marshrut, vaqt, kishi soni, telefon, profil, manba havolasi, «✅ Oldim», «💬 Yozish».
- **Dedup:** 45 daqiqa. Yetkazilmagan e'lon dublikat sanalmaydi.
- **Navbat:** ~18 xabar/daqiqa, tarmoq xatosida qayta urinish.
- **Eski xabarlar:** `MAX_AGE_MINUTES` dan eskisi e'lon qilinmaydi.
- **Buyurtma:** `/start`, `/order`, `/cancel`. Qayerdan, qayerga, qachon, telefon, tasdiq. Birdan yozilgan matndan ma'lumot oladi. `ORDER_COOLDOWN_SEC` cheklovi.
- **«Oldim»:** birinchi bosgan oladi, qolganlarga kim olgani aytiladi.
- **Bot orqali yozishuv:** faqat bot buyurtmalari uchun, `/chats`, `/end`. 24 soat jimlikda yoki restartda yopiladi. Yo'lovchining raqami haydovchiga ko'rinadi, haydovchiniki yo'lovchiga ko'rinmaydi.
- **`OFFER_IN_GROUPS=1`:** manba guruhda yo'lovchi xabariga shu guruhda javob bilan buyurtma tugmasi (kuniga 1 marta). Hozir o'chiq.
- **Moderatsiya (2026-11-06):** bot qo'shilgan istalgan guruhda ishlaydi (kuzatuvdan qat'i nazar, haydovchilar guruhidan tashqari). Kirdi-chiqdi xabarlarini o'chiradi. Reklamani ham o'chiradi: havola, begona @username (o'zining va botning @username'i mumkin), kanaldan forward, kanal nomidan yozish, havolali tugma, spam so'zlar, tahrirlangan xabar ham tekshiriladi. Flood: 10 soniyada 5 tadan ko'p xabar yoki 2 daqiqada bir xil matn 3 marta yozilsa, 5 daqiqaga cheklaydi. Ogohlantirish 20 soniyada o'chadi. Guruh adminlariga tegmaydi (ro'yxat 10 daqiqa keshda). `/settings` faqat guruh adminlari uchun: tugmalar va hisoblagichlar. Bot qo'shilganda salom va haydovchilarga yetkazish haqida ogohlantirish yozadi. Botga admin huquqi kerak.
- **Rol tanlash (2026-11-16):** `/start` da yo'lovchi/haydovchi tugmalari. Yo'lovchi → buyurtma oqimi. Haydovchi → ma'lumot. Rol `users.json` da. `?start=order` va `/start chat` buzilmaydi.
- **Yo'nalish filtri + hashtag (2026-11-16):** `routes.json` da xizmat yo'nalishlari bo'lsa, maxfiy guruhga faqat mos yo'nalishdagi e'lon tushadi (`pipeline.process` → `routes.allowed`). Noaniq yo'nalish `ROUTE_FILTER_STRICT=0` da o'tadi. E'longa yo'nalish hashtagi qo'shiladi (`#Toshkent_Termiz`, `pipeline.route_hashtag`) — filtrlab ko'rish uchun. Boshqaruv: `/menu` → "🧭 Yo'nalishlar".
- **Ko'p sessiyali haydovchi tizimi (2026-11-17):** eski bitta-akkauntli `/agregator` (aggregator.py) o'chirildi. Har haydovchi `🔐 Akkauntni ulash` orqali o'z akkauntini ulaydi; sessiya Fernet bilan shifrlangan. Tanlangan guruhlar (maks. `max_groups`) o'qiladi: yo'lovchi e'loni yopiq guruhga tushadi; bir xabar bir marta (`(chat,msg)` dedup), ulangan akkauntlarning o'z xabarlari va yopiq guruhlar o'qilmaydi. Rassilka: obuna (`has_access`) shart, guruhlar orasida `uniform(min_gap, min_gap+7)`, interval 15/30/60, kunlik `BROADCAST_MAX_PER_DAY`. Xatolar: FloodWait — kutish (>1 soat bo'lsa to'xtaydi), yozish taqiqlangan guruh — tanlovdan chiqariladi va haydovchiga aytiladi, sessiya bekor — bazadan o'chadi va ogohlantiriladi. Restartda `is_running` rassilkalar davom etadi.
- **Admin panel `/admin` (2026-11-17):** faqat `ADMIN_IDS`. Obuna +7/+30/♾/olish, blok (middleware ham to'xtatadi), sessiyani uzish, rassilkani majburan to'xtatish. Yo'nalish → yopiq guruh chat_id (ID, forward yoki 0=DRIVERS_CHAT_ID); yopiq guruhga yozib bo'lmasa e'lon DRIVERS_CHAT_ID ga tushadi. Sozlamalar `bot_settings` da: `max_groups`(12), `min_gap_sec`(5), `min_interval_min`(15), `global_stop`.
- **NLP tuzatish (2026-11-17):** haydovchi e'lonlari («Toshkentga ketaman, kim bor?», «4 joy bo'sh», «pochta olib ketaman», «yo'lovchi kerak») yo'lovchi deb maxfiy guruhga tushayotgan edi. `DRIVER_KW` ga «kim bor», «kimga kerak», «olib ketaman», «joy bosh», «bor joy»... qo'shildi, `FREE_SEATS_RE` (raqam + joy/o'rin) va kuchli haydovchi belgisi `ketaman` dan ustun.
- **Rejimlar:** `MODE=bot|userbot|both`. Userbot `/addgroup` bilan ochiq guruhga o'zi qo'shiladi. Taklif havolasi qo'llab-quvvatlanmaydi.

## `.env` kalitlari
`MODE, BOT_TOKEN, DRIVERS_CHAT_ID, SOURCE_CHATS, ADMIN_IDS, GROUPS_FILE, MOD_FILE, USERS_FILE, ROUTES_FILE, ROUTE_FILTER_STRICT, BROADCAST_MAX_PER_DAY, AI_MIN_CONFIDENCE, DB_FILE, SESSION_SECRET, FERNET_KEY_FILE, API_ID, API_HASH, SESSION_NAME, AI_API_KEY, AI_BASE_URL, AI_MODEL, DEDUP_MINUTES, SEND_INTERVAL_SEC, MAX_AGE_MINUTES, ORDER_COOLDOWN_SEC, OFFER_IN_GROUPS, USE_SYSTEM_CA`

`.env` qiymatlarini, tokenni, `*.session`, `fernet.key` va `taxi.db` ni chatga chiqarmang.

## Ishga tushirish va tekshirish
```bash
.venv/Scripts/python main.py
.venv/Scripts/python -m pytest -q tests        # 98 ta
.venv/Scripts/python tests/e2e_fake_telegram.py # 148 ta, real Telegram'ga ulanmaydi
```
Bitta token bilan bir vaqtda faqat bitta nusxa ishlashi kerak.

## Hozirgi holat
- Bot **to'xtatilgan** (foydalanuvchi so'rovi bilan).
- `.env`: `MODE=bot`, privacy o'chirilgan. `AI_API_KEY` bo'sh. `API_ID`/`API_HASH` hali namunadagi qiymatlar. `OFFER_IN_GROUPS` yozilmagan, ya'ni o'chiq.
- Kuzatuvda 2 guruh: `My mothly tasks` (test) va `SAFAR TAKSI | Surxondaryo Samarqand Qarshi Buxoro`.
- `DRIVERS_CHAT_ID` guruhi nomi **"My English contents"**. Haqiqiy haydovchilar guruhi ekani tasdiqlanmagan.
- Bot u guruhda oddiy a'zo, shuning uchun adminlarni ko'ra olmadi va `ADMIN_IDS` ishlatilmoqda. Botni u yerda admin qilish tavsiya etilgan (sinalmagan).

## Sinalmaganlar
- Userbot/Telethon real akkauntda, avtomatik qo'shilish.
- Yangi Groq modeli `openai/gpt-oss-20b` (kalit yo'q).
- `BUTTON_USER_PRIVACY_RESTRICTED`, «Oldim» orqali botni ochish, `copy_message`, relay: faqat soxta serverda sinalgan.
- Real haydovchilar guruhiga e'lon yetishi log orqali tasdiqlanmagan (`sent` log'ga yozilmaydi, foydalanuvchi o'zi ko'rishi kerak).

- Moderatsiya real guruhda sinalmagan, faqat soxta serverda.
- Kanal o'qish (bot-admin va userbot), tugmali panel, deep-link qo'shish — faqat soxta serverda sinalgan. Deep-link `?startchannel` real Telegram klientida tekshirilmagan.
- Haydovchi akkauntini ulash (kod, 2FA), ko'p sessiyali o'qish/tarqatish, `/admin`: faqat soxta Telethon/Telegram bilan sinalgan, REAL akkaunt bilan emas. Yangi talab: `pip install -r requirements.txt` (cryptography), `.env` da haqiqiy `API_ID`/`API_HASH` va `ADMIN_IDS`. AI hali real Groq kaliti bilan ishlatilmagan. Yo'nalish filtri/hashtag real guruh xabarlarida sinalmagan.

## Keyingi ishlar
0. Moderatsiyaning keyingi bosqichi: guruh egasiga haftalik hisobot, «faqat obunachi haydovchilar e'lon beradi» rejimi (obuna tizimidan keyin).
1. Foydalanuvchi aytgan «guruhga qo'shishda muammo»: aniq xato matni hali olinmagan. Bot log'ida xato yo'q edi, Telegram tomonida bo'lishi kerak.
2. Haydovchilar guruhini tasdiqlash.
3. Bot qo'shib bo'lmaydigan guruhlar uchun `MODE=both`: alohida akkaunt, `API_ID`/`API_HASH`, terminalda bir martalik login. Akkauntni bloklanish va qoidalar xavfi aytilgan.
4. VPS'ga ko'chirish (doimiy ishlash uchun).
5. Haqiqiy guruh xabarlari bo'yicha NLP'ni yaxshilash. Noaniq misol: `toshkent ketamiz srochni`.
6. Haydovchi olmagan buyurtma haqida yo'lovchini ogohlantirish (taklif qilingan, qilinmagan).

## Muhit xususiyatlari
- Windows, Git Bash va PowerShell. Bash heredoc apostrofli matnda buziladi: fayllarni Write bilan yozing.
- Tarmoqda Falcongaze SecureTower HTTPS'ni ushlab qolishi mumkin. `CERTIFICATE_VERIFY_FAILED` chiqsa SSL tekshiruvini o'chirmang, `USE_SYSTEM_CA=1` qiling.
- Git repo yo'q. NLP testlari qoidalar bilan birga yozilgan, haqiqiy aniqlikni ko'rsatmaydi.
