"""Bazaga murojaat funksiyalari. Handlerlar va servislar faqat shular orqali ishlaydi."""
import time

from database.models import DEFAULT_SETTINGS, conn

DAY = 86400


# ---------- users ----------
def touch_user(user_id: int, username: str | None, full_name: str | None):
    """Foydalanuvchini qo'shadi yoki ismini yangilaydi (har shaxsiy xabarda)."""
    now = time.time()
    conn().execute(
        "INSERT INTO users(user_id, username, full_name, created_at, last_seen) VALUES (?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name, "
        "last_seen=excluded.last_seen",
        (user_id, (username or "").lower() or None, full_name, now, now))


def get_user(user_id: int):
    return conn().execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def find_user(ref: str):
    """ID yoki @username bo'yicha qidiradi."""
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        return get_user(int(ref))
    uname = ref.lstrip("@").lower()
    return conn().execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()


def get_role(user_id: int) -> str | None:
    row = get_user(user_id)
    return row["role"] if row else None


def set_role(user_id: int, role: str):
    conn().execute("INSERT INTO users(user_id, role, created_at) VALUES (?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role", (user_id, role, time.time()))


def all_user_ids(role: str | None = None) -> list[int]:
    q, args = "SELECT user_id FROM users WHERE is_blocked=0", ()
    if role:
        q, args = q + " AND role=?", (role,)
    return [r[0] for r in conn().execute(q, args)]


def set_blocked(user_id: int, blocked: bool):
    conn().execute("UPDATE users SET is_blocked=? WHERE user_id=?", (int(blocked), user_id))


def is_blocked(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_blocked"])


# ---------- obuna ----------
def add_subscription(user_id: int, days: int, now: float | None = None):
    """Obunani uzaytiradi: tugamagan bo'lsa oxiridan, tugagan bo'lsa hozirdan."""
    now = time.time() if now is None else now
    row = get_user(user_id)
    base = max(now, row["sub_until"] or 0) if row else now
    conn().execute("UPDATE users SET sub_until=? WHERE user_id=?", (base + days * DAY, user_id))


def set_unlimited(user_id: int, on: bool):
    conn().execute("UPDATE users SET sub_unlimited=? WHERE user_id=?", (int(on), user_id))


def revoke_subscription(user_id: int):
    conn().execute("UPDATE users SET sub_until=NULL, sub_unlimited=0 WHERE user_id=?", (user_id,))


def has_access(user_id: int, now: float | None = None) -> bool:
    """Rassilkani yoqish huquqi: blokda emas va obuna amalda (yoki cheksiz)."""
    now = time.time() if now is None else now
    row = get_user(user_id)
    if not row or row["is_blocked"]:
        return False
    return bool(row["sub_unlimited"] or (row["sub_until"] and row["sub_until"] > now))


def sub_text(row, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if row is None:
        return "yo'q"
    if row["sub_unlimited"]:
        return "♾ cheksiz"
    if row["sub_until"] and row["sub_until"] > now:
        left = row["sub_until"] - now
        return f"✅ {time.strftime('%d.%m.%Y %H:%M', time.localtime(row['sub_until']))} gacha ({int(left // DAY)} kun)"
    return "❌ yo'q / tugagan"


# ---------- user_sessions ----------
def save_session(user_id: int, phone: str, session_enc: str, tg_user_id: int, tg_username: str | None,
                 tg_name: str):
    conn().execute(
        "INSERT INTO user_sessions(user_id, phone, session_enc, tg_user_id, tg_username, tg_name, created_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone, "
        "session_enc=excluded.session_enc, tg_user_id=excluded.tg_user_id, tg_username=excluded.tg_username, "
        "tg_name=excluded.tg_name",
        (user_id, phone, session_enc, tg_user_id, tg_username, tg_name, time.time()))


def get_session(user_id: int):
    return conn().execute("SELECT * FROM user_sessions WHERE user_id=?", (user_id,)).fetchone()


def all_sessions():
    return conn().execute("SELECT * FROM user_sessions").fetchall()


def delete_session(user_id: int):
    conn().execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))     # guruhlar CASCADE bilan


def set_ad_text(user_id: int, text: str):
    conn().execute("UPDATE user_sessions SET ad_text=? WHERE user_id=?", (text.strip(), user_id))


def set_interval(user_id: int, minutes: int):
    conn().execute("UPDATE user_sessions SET interval_min=? WHERE user_id=?", (minutes, user_id))


def set_running(user_id: int, on: bool):
    conn().execute("UPDATE user_sessions SET is_running=? WHERE user_id=?", (int(on), user_id))


def stop_all_running():
    conn().execute("UPDATE user_sessions SET is_running=0")


def start_round(user_id: int, now: float | None = None) -> int:
    """Siklni belgilaydi, bugungi sikllar sonini qaytaradi."""
    now = time.time() if now is None else now
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    c = conn()
    row = get_session(user_id)
    n = (row["rounds_today"] if row and row["day"] == today else 0) + 1
    c.execute("UPDATE user_sessions SET last_round=?, day=?, rounds_today=? WHERE user_id=?",
              (now, today, n, user_id))
    return n


def rounds_today(user_id: int, now: float | None = None) -> int:
    now = time.time() if now is None else now
    row = get_session(user_id)
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    return row["rounds_today"] if row and row["day"] == today else 0


# ---------- session_groups ----------
def sync_groups(user_id: int, items: list[tuple[int, str]]):
    """Akkaunt guruhlari ro'yxatini yangilaydi, tanlanganlarini saqlab qoladi."""
    c = conn()
    ids = {cid for cid, _ in items}
    for cid, title in items:
        c.execute("INSERT INTO session_groups(user_id, chat_id, title) VALUES (?,?,?) "
                  "ON CONFLICT(user_id, chat_id) DO UPDATE SET title=excluded.title", (user_id, cid, title))
    for (cid,) in c.execute("SELECT chat_id FROM session_groups WHERE user_id=?", (user_id,)).fetchall():
        if cid not in ids:
            c.execute("DELETE FROM session_groups WHERE user_id=? AND chat_id=?", (user_id, cid))


def groups(user_id: int):
    return conn().execute("SELECT chat_id, title, selected FROM session_groups WHERE user_id=? "
                          "ORDER BY selected DESC, title COLLATE NOCASE", (user_id,)).fetchall()


def selected_groups(user_id: int) -> list[tuple[int, str]]:
    return [(r[0], r[1]) for r in conn().execute(
        "SELECT chat_id, title FROM session_groups WHERE user_id=? AND selected=1 ORDER BY title COLLATE NOCASE",
        (user_id,))]


def toggle_group(user_id: int, chat_id: int, limit: int) -> str:
    """'on', 'off', 'limit' (chegaradan oshdi) yoki 'missing'."""
    c = conn()
    row = c.execute("SELECT selected FROM session_groups WHERE user_id=? AND chat_id=?",
                    (user_id, chat_id)).fetchone()
    if row is None:
        return "missing"
    if not row[0] and len(selected_groups(user_id)) >= limit:
        return "limit"
    c.execute("UPDATE session_groups SET selected=? WHERE user_id=? AND chat_id=?",
              (int(not row[0]), user_id, chat_id))
    return "off" if row[0] else "on"


def unselect_group(user_id: int, chat_id: int):
    conn().execute("UPDATE session_groups SET selected=0 WHERE user_id=? AND chat_id=?", (user_id, chat_id))


def all_selected_chat_ids() -> dict[int, set[int]]:
    """{user_id: {chat_id, ...}} — o'qish uchun."""
    out: dict[int, set[int]] = {}
    for uid, cid in conn().execute("SELECT user_id, chat_id FROM session_groups WHERE selected=1"):
        out.setdefault(uid, set()).add(cid)
    return out


# ---------- post_log ----------
def record_post(user_id: int, chat_id: int, now: float | None = None):
    now = time.time() if now is None else now
    c = conn()
    c.execute("INSERT INTO post_log(user_id, chat_id, ts) VALUES (?,?,?)", (user_id, chat_id, now))
    c.execute("DELETE FROM post_log WHERE ts < ?", (now - 2 * DAY,))


def report(user_id: int, now: float | None = None) -> list[tuple[str, int]]:
    now = time.time() if now is None else now
    rows = conn().execute(
        "SELECT COALESCE(g.title, CAST(p.chat_id AS TEXT)), COUNT(*) FROM post_log p "
        "LEFT JOIN session_groups g ON g.user_id=p.user_id AND g.chat_id=p.chat_id "
        "WHERE p.user_id=? AND p.ts>=? GROUP BY p.chat_id ORDER BY COUNT(*) DESC", (user_id, now - DAY)).fetchall()
    return [(r[0], r[1]) for r in rows]


# ---------- routes ----------
def all_routes():
    return conn().execute("SELECT * FROM routes ORDER BY id").fetchall()


def get_route(route_id: int):
    return conn().execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()


def add_route(a: str, b: str, chat_id: int | None = None, title: str = "") -> int:
    cur = conn().execute("INSERT INTO routes(city_a, city_b, chat_id, title) VALUES (?,?,?,?)",
                         (a, b, chat_id, title))
    return cur.lastrowid


def set_route_chat(route_id: int, chat_id: int | None, title: str = ""):
    conn().execute("UPDATE routes SET chat_id=?, title=? WHERE id=?", (chat_id, title, route_id))


def delete_route(route_id: int) -> bool:
    return conn().execute("DELETE FROM routes WHERE id=?", (route_id,)).rowcount > 0


# ---------- bot_settings ----------
def get_setting(key: str) -> int:
    row = conn().execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
    return int(row[0]) if row else int(DEFAULT_SETTINGS[key])


def set_setting(key: str, value: int):
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    conn().execute("INSERT INTO bot_settings(key, value) VALUES (?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(int(value))))


# ---------- statistika ----------
def counts(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    c = conn()
    one = lambda q, *a: c.execute(q, a).fetchone()[0]       # noqa: E731
    return {
        "users": one("SELECT COUNT(*) FROM users"),
        "drivers": one("SELECT COUNT(*) FROM users WHERE role='driver'"),
        "passengers": one("SELECT COUNT(*) FROM users WHERE role='passenger'"),
        "blocked": one("SELECT COUNT(*) FROM users WHERE is_blocked=1"),
        "subscribed": one("SELECT COUNT(*) FROM users WHERE sub_unlimited=1 OR sub_until>?", now),
        "sessions": one("SELECT COUNT(*) FROM user_sessions"),
        "posts_24h": one("SELECT COUNT(*) FROM post_log WHERE ts>=?", now - DAY),
    }
