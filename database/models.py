"""SQLite sxemasi va ulanish.

Jadvallar:
  users           — bot foydalanuvchilari: rol, obuna muddati, blok
  user_sessions   — haydovchining Telegram akkaunti: shifrlangan StringSession, e'lon matni, interval, holat
  session_groups  — haydovchi akkaunti a'zo bo'lgan guruhlar va tanlanganlari (selected=1)
  post_log        — tarqatilgan e'lonlar (hisobot uchun, 24 soat)
  routes          — yo'nalish (ikki shahar) va unga biriktirilgan yopiq guruh chat_id si
  bot_settings    — admin paneldan o'zgaradigan limitlar (kalit-qiymat)

Bot bitta jarayonda ishlaydi, so'rovlar mikrosoniyalik — shuning uchun oddiy sqlite3 (sinxron) yetarli.
"""
import json
import logging
import sqlite3
import time

import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    full_name     TEXT,
    role          TEXT,                       -- passenger | driver | NULL
    sub_until     REAL,                       -- obuna tugash vaqti (epoch). NULL = obuna yo'q
    sub_unlimited INTEGER NOT NULL DEFAULT 0, -- 1 = cheksiz ruxsat
    is_blocked    INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    last_seen     REAL
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id       INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    phone         TEXT,
    session_enc   TEXT NOT NULL,              -- Fernet bilan shifrlangan Telethon StringSession
    tg_user_id    INTEGER,
    tg_username   TEXT,
    tg_name       TEXT,
    ad_text       TEXT NOT NULL DEFAULT '',
    interval_min  INTEGER NOT NULL DEFAULT 30,
    is_running    INTEGER NOT NULL DEFAULT 0, -- restartdan keyin rassilka davom etsinmi
    last_round    REAL NOT NULL DEFAULT 0,
    day           TEXT NOT NULL DEFAULT '',
    rounds_today  INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS session_groups (
    user_id   INTEGER NOT NULL REFERENCES user_sessions(user_id) ON DELETE CASCADE,
    chat_id   INTEGER NOT NULL,
    title     TEXT NOT NULL DEFAULT '',
    selected  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS post_log (
    user_id  INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_post_log_ts ON post_log(ts);

CREATE TABLE IF NOT EXISTS routes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    city_a   TEXT NOT NULL,
    city_b   TEXT NOT NULL,
    chat_id  INTEGER,                         -- yopiq guruh. NULL = DRIVERS_CHAT_ID
    title    TEXT NOT NULL DEFAULT ''         -- yopiq guruh nomi (ko'rsatish uchun)
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

# Admin paneldan o'zgaradigan sozlamalar va standart qiymatlari
DEFAULT_SETTINGS = {
    "max_groups": 12,           # bitta haydovchi tanlay oladigan guruhlar soni
    "min_gap_sec": 5,           # guruhlar orasidagi minimal pauza (maksimal = min + 7)
    "min_interval_min": 15,     # haydovchi tanlay oladigan eng qisqa interval
    "global_stop": 0,           # 1 = hamma rassilka to'xtatilgan, yangisini ham yoqib bo'lmaydi
}

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_FILE, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.executescript(SCHEMA)
        _migrate_json(_conn)
    return _conn


def close():
    """Testlar uchun: keyingi conn() yangi faylni ochadi."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _migrate_json(c: sqlite3.Connection):
    """Eski users.json / routes.json bir marta bazaga ko'chiriladi (fayllar o'chirilmaydi)."""
    now = time.time()
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 and config.USERS_FILE.exists():
        try:
            data = json.loads(config.USERS_FILE.read_text(encoding="utf-8"))
            for uid, v in data.items():
                c.execute("INSERT OR IGNORE INTO users(user_id, role, created_at) VALUES (?,?,?)",
                          (int(uid), v.get("role"), now))
            log.info("users.json bazaga ko'chirildi: %d ta", len(data))
        except (OSError, ValueError) as e:
            log.error("users.json ko'chirilmadi: %s", e)
    if c.execute("SELECT COUNT(*) FROM routes").fetchone()[0] == 0 and config.ROUTES_FILE.exists():
        try:
            data = json.loads(config.ROUTES_FILE.read_text(encoding="utf-8"))
            for a, b in data:
                c.execute("INSERT INTO routes(city_a, city_b) VALUES (?,?)", (a, b))
            log.info("routes.json bazaga ko'chirildi: %d ta", len(data))
        except (OSError, ValueError) as e:
            log.error("routes.json ko'chirilmadi: %s", e)
