import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name, default=0):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"Xato: .env dagi {name} butun son bo'lishi kerak (hozir: {raw!r})")


def _float(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        sys.exit(f"Xato: .env dagi {name} son bo'lishi kerak (hozir: {raw!r})")


def _list(name):
    out = []
    for x in os.getenv(name, "").split(","):
        x = x.strip()
        if x:
            out.append(int(x) if x.lstrip("-").isdigit() else x)  # id yoki @username
    return out


MODE = os.getenv("MODE", "bot").strip().lower()     # bot | userbot | both

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DRIVERS_CHAT_ID = _int("DRIVERS_CHAT_ID")
# Faqat birinchi ishga tushirishda groups.json ga ko'chiriladi. Keyin guruhlar bot orqali boshqariladi.
SOURCE_CHATS = _list("SOURCE_CHATS")
# Haydovchilar guruhi adminlari avtomatik bot admini. Bu yerda qo'shimcha user ID lar berish mumkin.
ADMIN_IDS = {x for x in _list("ADMIN_IDS") if isinstance(x, int)}
# «Admin bilan bog'lanish» tugmasi uchun @username. Bo'sh bo'lsa ADMIN_IDS dagi birinchi adminning username'i olinadi
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip().lstrip("@")
GROUPS_FILE = Path(os.getenv("GROUPS_FILE", "").strip() or BASE_DIR / "groups.json")
# Guruh moderatsiyasi sozlamalari va hisoblagichlari
MOD_FILE = Path(os.getenv("MOD_FILE", "").strip() or BASE_DIR / "moderation.json")
# Foydalanuvchi rollari (yo'lovchi/haydovchi)
USERS_FILE = Path(os.getenv("USERS_FILE", "").strip() or BASE_DIR / "users.json")
# Xizmat qilinadigan yo'nalishlar (maxfiy guruhga faqat shular yuboriladi)
ROUTES_FILE = Path(os.getenv("ROUTES_FILE", "").strip() or BASE_DIR / "routes.json")
# 1 = yo'nalishi aniqlanmagan e'lonlar ham filtrdan o'tmaydi. 0 = ularni o'tkazadi (e'lon yo'qotmaslik uchun)
ROUTE_FILTER_STRICT = os.getenv("ROUTE_FILTER_STRICT", "").strip().lower() in ("1", "true", "yes")

# Haydovchi rassilkasi: bitta haydovchi uchun kunlik maksimal sikl (pauza va interval /admin -> Sozlamalar da)
BROADCAST_MAX_PER_DAY = _int("BROADCAST_MAX_PER_DAY", 40)

# SQLite baza: foydalanuvchilar (obuna), haydovchi sessiyalari, yo'nalishlar, sozlamalar
DB_FILE = Path(os.getenv("DB_FILE", "").strip() or BASE_DIR / "taxi.db")
# Haydovchi sessiyalarini shifrlash kaliti (Fernet). Bo'sh bo'lsa fernet.key fayli avtomatik yaratiladi.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
FERNET_KEY_FILE = Path(os.getenv("FERNET_KEY_FILE", "").strip() or BASE_DIR / "fernet.key")

# Userbot (my.telegram.org dan olinadi)
API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_NAME = os.getenv("SESSION_NAME", "userbot").strip() or "userbot"

# Bepul AI (OpenAI-mos). Default: Groq
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.groq.com/openai/v1").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip() or "openai/gpt-oss-20b"
# AI shundan past ishonch bilan javob bersa, uning natijasi qabul qilinmaydi (noaniq xabar tashlanadi)
AI_MIN_CONFIDENCE = _float("AI_MIN_CONFIDENCE", 0.6)

DEDUP_MINUTES = _int("DEDUP_MINUTES", 45)
SEND_INTERVAL_SEC = _float("SEND_INTERVAL_SEC", 3.2)  # ~18 xabar/daqiqa
MAX_AGE_MINUTES = _int("MAX_AGE_MINUTES", 15)         # bot o'chiq paytdagi eski xabarlarni e'lon qilmaslik
ORDER_COOLDOWN_SEC = _int("ORDER_COOLDOWN_SEC", 120)  # bir odam haydovchilar guruhini to'ldirmasin
OFFER_IN_GROUPS = os.getenv("OFFER_IN_GROUPS", "").strip().lower() in ("1", "true", "yes")
MAX_LEN = 700                                         # uzun reklamalarni o'tkazib yuborish

# Korporativ tarmoqda (TLS tekshiruvi bor joyda) certifi o'rniga Windows/OS sertifikatlari ishlatiladi
USE_SYSTEM_CA = os.getenv("USE_SYSTEM_CA", "").strip().lower() in ("1", "true", "yes")


def validate():
    """Noto'g'ri sozlamani traceback o'rniga tushunarli xabar bilan to'xtatadi."""
    errors = []
    if MODE not in ("bot", "userbot", "both"):
        errors.append(f"MODE bot, userbot yoki both bo'lishi kerak (hozir: {MODE!r})")
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN bo'sh (@BotFather dan oling)")
    if not DRIVERS_CHAT_ID:
        errors.append("DRIVERS_CHAT_ID bo'sh (botni guruhga qo'shib, /id yozing)")
    if MODE in ("userbot", "both") and not (API_ID and API_HASH):
        errors.append("userbot rejimi uchun API_ID va API_HASH kerak (my.telegram.org)")
    if errors:
        sys.exit("Sozlamada xato (.env):\n- " + "\n- ".join(errors))
