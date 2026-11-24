"""Botni kuzatish: nima ishlayapti, nima ishlamayapti — loglarni o'qimasdan, /admin → «🩺 Diagnostika» da.

Yig'iladi (restartdan beri, xotirada):
- e'lonlar: oxirgi yuborilgan vaqt, soatlik son
- mention: urinishlar, muvaffaqiyat, har bir muvaffaqiyatsizlik SABABI va qaysi manba guruhda ko'p
- xatolar: ERROR/WARNING loglarining oxirgi 15 tasi
Qorovul (watchdog): kunduzi (07–23) 30 daqiqa e'lon chiqmasa, userbot o'chsa yoki mention ulushi tushib
ketsa — adminlarga o'zi xabar yuboradi (bir xil ogohlantirish 2 soatda bir martadan ko'p emas).
"""
import asyncio
import logging
import time
from collections import Counter, deque
from datetime import datetime

log = logging.getLogger(__name__)
STARTED = time.time()

sent_times: deque = deque(maxlen=2000)          # yuborilgan e'lonlar vaqti
mention = Counter()                              # ok / no_userbot / not_member / unknown_user / ...
mention_fail_src: Counter = Counter()            # muvaffaqiyatsiz mention: manba guruh -> soni
errors: deque = deque(maxlen=15)                 # (vaqt, daraja, matn)
_alerted: dict[str, float] = {}
_bug_times: deque = deque(maxlen=50)
_bug_dropped = {"n": 0}

REASONS = {
    "ok": "✅ qo'yildi",
    "not_member": "userbot manba guruhga a'zo emas",
    "unknown_user": "userbot mijozni taniy olmadi",
    "stripped": "Telegram mention'ni olib tashladi",
    "closed_missing": "userbot yopiq guruhda yo'q",
    "no_userbot": "userbot ishlamayapti",
    "error": "boshqa xato",
}


def record_sent():
    sent_times.append(time.time())


_bot = {"bot": None}


def set_bot(bot):
    _bot["bot"] = bot


def _msg_link(chat_id, msg_id) -> str | None:
    s = str(chat_id or "")
    return f"https://t.me/c/{s[4:]}/{msg_id}" if s.startswith("-100") and msg_id else None


def record_mention(result: str, src_chat=None, src_title: str | None = None, info: dict | None = None,
                   ad_chat=None, ad_msg=None):
    mention[result] += 1
    if result != "ok" and src_chat:
        key = f"{src_title or ''} ({src_chat})".strip()
        if key in mention_fail_src or len(mention_fail_src) < 200:     # xotira: ko'pi bilan 200 ta guruh
            mention_fail_src[key] += 1
    if result != "ok":
        import html
        i = info or {}
        e = html.escape
        ad = _msg_link(ad_chat, ad_msg)
        lines = ["🐞 <b>Mention qo'yilmadi</b>",
                 f"Sabab: <b>{e(REASONS.get(result, result))}</b>",
                 f"Manba guruh: {e(src_title or '?')} (<code>{src_chat}</code>)"]
        if i.get("src_link"):
            lines.append(f'Asl xabar: <a href="{e(i["src_link"], quote=True)}">ochish</a>')
        if ad:
            lines.append(f'Bizdagi e\'lon: <a href="{ad}">ochish</a>')
        lines.append(f"Mijoz: {e(str(i.get('name') or '—'))} · ID <code>{i.get('user_id')}</code>")
        hint = {"not_member": "➡️ Userbotni shu manba guruhga qo'shing.",
                "closed_missing": "➡️ Userbotni yopiq guruhingizga qo'shing.",
                "no_userbot": "➡️ Userbot ishlamayapti: serverda logni tekshiring."}.get(result)
        if hint:
            lines.append(hint)
        to_bugs("\n".join(lines))


def to_bugs(text: str):
    """Xatolar guruhiga (admin panel → ⚙️ → 🐞) yuboradi. Guruh tanlanmagan bo'lsa — jim."""
    try:
        from database import crud
        chat = crud.get_setting("bugs_chat_id")
    except Exception:
        return
    bot = _bot["bot"]
    if not chat or bot is None:
        return
    # Cheklov: 10 daqiqada ko'pi bilan 15 ta xabar (Telegram limiti va xotira uchun); ortig'i sanab boriladi
    now = time.time()
    while _bug_times and now - _bug_times[0] > 600:
        _bug_times.popleft()
    if len(_bug_times) >= 15:
        _bug_dropped["n"] += 1
        return
    if _bug_dropped["n"]:
        text = f"<i>(+{_bug_dropped['n']} ta xabar ko'pligi sababli o'tkazib yuborildi — Diagnostika'da hisobi bor)</i>\n" + text
        _bug_dropped["n"] = 0
    _bug_times.append(now)

    async def _go():
        try:
            await bot.send_message(chat, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as ex:
            log.info("[health] xatolar guruhiga yozilmadi: %s", str(ex)[:100])
    try:
        asyncio.get_running_loop().create_task(_go())
    except RuntimeError:
        pass


class ErrorTap(logging.Handler):
    """WARNING va undan yuqori loglarni xotirada saqlaydi (diagnostika uchun)."""

    def emit(self, record):
        try:
            if record.levelno >= logging.WARNING and record.name != __name__:
                errors.append((record.created, record.levelname, record.getMessage()[:180]))
        except Exception:
            pass


def install():
    logging.getLogger().addHandler(ErrorTap())


def _ago(ts) -> str:
    if not ts:
        return "hech qachon"
    m = int((time.time() - ts) // 60)
    return f"{m} daq oldin" if m < 120 else f"{m // 60} soat oldin"


def report() -> str:
    import admin
    from services import userbot_coverage as cov
    from services.broadcaster import manager
    now = time.time()
    last_hour = sum(1 for t in sent_times if now - t < 3600)
    lines = ["🩺 <b>Diagnostika</b> (restartdan beri: " + _ago(STARTED).replace(" oldin", "") + ")\n"]
    lines.append(f"📤 Oxirgi e'lon: {_ago(sent_times[-1] if sent_times else None)} · oxirgi soatda: {last_hour}")
    lines.append(f"🤖 Userbot: {'✅ ishlayapti' if admin.userbot is not None else '❌ ishlamayapti'}")
    cs = cov.status
    if cs.get("needed") is not None:
        lines.append(f"👁 Qamrov: {cs['needed'] - cs['missing']}/{cs['needed']} guruh · "
                     f"kuzatuvchi akkauntlar: {manager.live_count()}")
    total = sum(mention.values())
    if total:
        ok = mention["ok"]
        lines.append(f"\n💬 <b>Mention</b>: {ok}/{total} ({ok * 100 // total}%)")
        for k, n in mention.most_common():
            if k != "ok":
                lines.append(f"   • {REASONS.get(k, k)}: {n}")
        if mention_fail_src:
            lines.append("   Ko'p muvaffaqiyatsiz manbalar (userbotni shularga qo'shing):")
            for src, n in mention_fail_src.most_common(5):
                lines.append(f"   – {src}: {n}")
    else:
        lines.append("\n💬 Mention: hali urinish bo'lmagan")
    if errors:
        lines.append("\n⚠️ <b>Oxirgi ogohlantirishlar</b>:")
        for ts, lvl, msg in list(errors)[-6:]:
            import html
            lines.append(f"<code>{datetime.fromtimestamp(ts):%H:%M}</code> {html.escape(msg[:140])}")
    return "\n".join(lines)


async def _alert(bot, key: str, text: str):
    import config
    if time.time() - _alerted.get(key, 0) < 2 * 3600:
        return
    _alerted[key] = time.time()
    to_bugs("🚨 " + text)
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, "🚨 " + text + "\n\nBatafsil: /admin → 🩺 Diagnostika")
        except Exception:
            pass
    log.warning("[health] %s", text)


async def watchdog(bot):
    import admin
    set_bot(bot)
    await asyncio.sleep(15 * 60)                 # ishga tushgach hamma narsa ulanib olsin
    while True:
        try:
            now = time.time()
            hour = datetime.now().hour
            last = sent_times[-1] if sent_times else STARTED
            if 7 <= hour < 23 and now - last > 30 * 60:
                await _alert(bot, "nosent", f"{int((now - last) // 60)} daqiqadan beri yopiq guruhga e'lon "
                                            "yuborilmadi. Bot xabarlarni o'qiyaptimi — tekshiring.")
            if admin.userbot is None:
                await _alert(bot, "userbot", "Userbot ishlamayapti: mention va guruhlarni o'qish to'xtagan.")
            total = sum(mention.values())
            if total >= 10 and mention["ok"] * 100 // total < 50:
                await _alert(bot, "mention", f"Mention faqat {mention['ok']}/{total} e'londa qo'yildi. "
                                             "Asosiy sabab Diagnostika bo'limida.")
        except Exception as e:
            log.error("[health] watchdog: %s", e)
        await asyncio.sleep(5 * 60)
