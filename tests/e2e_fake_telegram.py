"""Soxta Telegram + soxta AI server bilan to'liq oqim. Real .env token ishlatilmaydi."""
import asyncio, json, os, re, sys, tempfile, time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ.update(BOT_TOKEN="123456:TESTTOKENTESTTOKENTESTTOKEN", DRIVERS_CHAT_ID="-1009999", MODE="bot",
                  SOURCE_CHATS="", SEND_INTERVAL_SEC="0.05", ORDER_COOLDOWN_SEC="120", OFFER_IN_GROUPS="0", AI_API_KEY="fake", USE_SYSTEM_CA="",
                  AI_BASE_URL="http://127.0.0.1:18081/v1", GROUPS_FILE=str(tmp / "groups.json"), ADMIN_IDS="1",
                  MOD_FILE=str(tmp / "moderation.json"), USERS_FILE=str(tmp / "users.json"),
                  ROUTES_FILE=str(tmp / "routes.json"), DB_FILE=str(tmp / "taxi.db"),
                  FERNET_KEY_FILE=str(tmp / "fernet.key"), SESSION_SECRET="", API_ID="1", API_HASH="x", ADMIN_USERNAME="@admin_jasur",
                  BROADCAST_MAX_PER_DAY="2")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aiohttp import web
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import main as m
import pipeline, store

ADMIN, STRANGER = 1, 2
U = lambda i, n="Ali": {"id": i, "is_bot": False, "first_name": n}
G = lambda i=-100111: {"id": i, "type": "supergroup", "title": f"G{i}"}
PRIV = lambda i=ADMIN: {"id": i, "type": "private", "first_name": "A"}
mid = [100]


def msg(text, chat=None, user=None, age=0):
    mid[0] += 1
    return {"message": {"message_id": mid[0], "date": int(time.time()) - age, "chat": chat or G(),
                        "from": user or U(ADMIN), "text": text}}


def cbq(i, u, data="take", message=None):
    return {"callback_query": {"id": str(i), "from": u, "chat_instance": "x", "data": data,
                               "message": message or dict(CBM)}}


def ent_(text, piece, type_="mention"):
    return {"type": type_, "offset": text.index(piece), "length": len(piece)}


def joined(chat, by):
    return {"my_chat_member": {"chat": chat, "from": by, "date": int(time.time()),
                               "old_chat_member": {"status": "left", "user": U(99)},
                               "new_chat_member": {"status": "member", "user": U(99)}}}


CBM = {"message_id": 777, "date": 1, "chat": G(-1009999), "from": {"id": 99, "is_bot": True, "first_name": "b"},
       "text": "YO'LOVCHI\nX", "entities": [{"type": "bold", "offset": 0, "length": 9}]}
sent, edits, answers, pending = [], [], [], []
copied, markups, rejected, ans_urls = [], [], [], []
deleted, restricted = [], []
BLOCKED, HIDDEN = {24}, {61, 62}
last_edit = {}
fail = []       # navbatdagi sendMessage javoblari: 400 yoki 500
stored = {}
ai_calls = [0]
uid = [1]
ALLOWED = re.compile(r"</?(b|i|a|code|blockquote)(\s[^>]*)?>")
ADMIN_CM = {"status": "administrator", "user": {"id": 99, "is_bot": True, "first_name": "b"}, "can_be_edited": False,
            "is_anonymous": False, "can_manage_chat": True, "can_delete_messages": True, "can_manage_video_chats": True,
            "can_restrict_members": True, "can_promote_members": False, "can_change_info": True, "can_invite_users": True,
            "can_post_messages": True, "can_post_stories": False, "can_edit_stories": False, "can_delete_stories": False,
            "can_send_welcome_messages": False}


async def api(req):
    meth = req.match_info["m"]
    d = await req.json() if req.content_type == "application/json" else dict(await req.post())
    ok = lambda r: web.json_response({"ok": True, "result": r})
    bad = lambda c, s: web.json_response({"ok": False, "error_code": c, "description": s}, status=c)
    if meth == "getMe":
        return ok({"id": 99, "is_bot": True, "first_name": "b", "username": "b_bot",
                   "can_read_all_group_messages": False})
    if meth == "deleteWebhook":
        return ok(True)
    if meth == "getChat":
        c = str(d["chat_id"])
        extra = {"accent_color_id": 0, "max_reaction_count": 0, "accepted_gift_types": {"unlimited_gifts": False, "limited_gifts": False, "unique_gifts": False, "premium_subscription": False, "gifts_from_channels": False}}
        if c == "@nope":
            return bad(400, "Bad Request: chat not found")
        if c == "@notmember":
            return ok({"id": -100444, "type": "supergroup", "title": "Begona", "username": "notmember", **extra})
        if c in ("@taksi_kanal", "-100222"):        # kanal
            return ok({"id": -100222, "type": "channel", "title": "Taksi Kanal", "username": "taksi_kanal", **extra})
        if c == "-100223":                          # bot admin bo'lmagan kanal
            return ok({"id": -100223, "type": "channel", "title": "Begona Kanal", "username": None, **extra})
        return ok({"id": -100333 if c.startswith("@") else int(c), "type": "supergroup", "title": "Yangi guruh",
                   "username": c[1:] if c.startswith("@") else None, **extra})
    if meth == "getChatMember":
        u, c = int(d["user_id"]), str(d["chat_id"])
        if u in (99, 123456):
            if c == "-100222":
                return ok(ADMIN_CM)                 # bot kanalda admin
            if c in ("-100444", "-100223"):
                return ok({"status": "left", "user": U(99)})
            return ok({"status": "member", "user": U(99)})
        if u == ADMIN:
            return ok({"status": "creator", "user": U(u), "is_anonymous": False})
        return ok({"status": "member", "user": U(u)})
    if meth == "getUpdates":
        if pending:
            u = pending.pop(0)
            uid[0] += 1
            return ok([{"update_id": uid[0], **u}])
        await asyncio.sleep(.05)
        return ok([])
    if meth == "copyMessage":
        if int(d["chat_id"]) in BLOCKED:
            return bad(403, "Forbidden: bot was blocked by the user")
        copied.append((str(d["chat_id"]), str(d["from_chat_id"]), str(d["message_id"])))
        return ok({"message_id": 1})
    if meth == "sendMessage":
        t = d["text"]
        rm = d.get("reply_markup") or ""
        rm = rm if isinstance(rm, str) else json.dumps(rm)
        if str(d["chat_id"]).lstrip("-").isdigit() and int(d["chat_id"]) in BLOCKED:
            return bad(403, "Forbidden: bot can't initiate conversation with a user")
        if "tg://user?id=" in rm and any(f"tg://user?id={x}" in rm for x in HIDDEN):
            rejected.append(t)
            return bad(400, "Bad Request: BUTTON_USER_PRIVACY_RESTRICTED")
        markups.append((str(d["chat_id"]), rm))
        if fail:
            c = fail.pop(0)
            sent.append((f"FAILED-{c}", t))
            return bad(c, "simulated")
        junk = [x for x in re.findall(r"<[^>]*>", t) if not ALLOWED.fullmatch(x)]
        if d.get("parse_mode") == "HTML" and junk:
            sent.append(("REJECTED", t))
            return bad(400, "Bad Request: can't parse entities")
        sent.append((d["chat_id"], t))
        return ok({"message_id": len(sent) + 500, "date": 1, "chat": G(int(d["chat_id"])), "text": t})
    if meth == "editMessageText":
        t = d["text"]
        if stored.get("t") == t:
            edits.append(("ERR not modified", t))
            return bad(400, "Bad Request: message is not modified")
        stored["t"] = t
        last_edit["rm"] = d.get("reply_markup")
        edits.append(("OK", t[:70]))
        return ok({**CBM, "text": t})
    if meth == "getChatAdministrators":
        return ok([{"status": "creator", "user": U(ADMIN), "is_anonymous": False}])
    if meth == "deleteMessage":
        deleted.append((str(d["chat_id"]), str(d["message_id"])))
        return ok(True)
    if meth == "restrictChatMember":
        restricted.append((str(d["chat_id"]), str(d["user_id"])))
        return ok(True)
    if meth == "answerCallbackQuery":
        answers.append(d.get("text"))
        ans_urls.append(d.get("url"))
        return ok(True)
    return bad(400, "unknown " + meth)


async def ai(req):
    ai_calls[0] += 1
    t = (await req.json())["messages"][-1]["content"]
    r = {"Nukus AI_GOOD": {"label": "passenger", "from": "Нукус", "to": "Хива", "seats": 1, "time": None},
         "Nukus AI_INT": {"label": "passenger", "from": 123, "to": "Buxoro", "seats": None, "time": None},
         "Nukus AI_LIST": [{"label": "passenger"}],
         "Nukus AI_TAG": {"label": "passenger", "from": "A", "to": "B", "seats": "<x>", "time": None},
         }.get(t, {"label": "other"})
    return web.json_response({"choices": [{"message": {"content": json.dumps(r)}}]})


async def serve(app, p):
    r = web.AppRunner(app)
    await r.setup()
    await web.TCPSite(r, "127.0.0.1", p).start()


async def step(*us):
    pending.extend(us)
    while pending:
        await asyncio.sleep(.02)
    await asyncio.sleep(.35)


mark = [0]
passed = []


def check(title, cond, extra=""):
    passed.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + title, extra if not cond else "", flush=True)


def new():
    out = sent[mark[0]:]
    mark[0] = len(sent)
    return out


async def run():
    a = web.Application(); a.router.add_post("/bot{tok}/{m}", api); await serve(a, 18080)
    b = web.Application(); b.router.add_post("/v1/chat/completions", ai); await serve(b, 18081)
    orig = Bot
    m.Bot = lambda tok: orig(tok, session=AiohttpSession(api=TelegramAPIServer.from_base("http://127.0.0.1:18080")))
    task = asyncio.create_task(m.main()); task.add_done_callback(lambda t: (print("MAIN DIED", repr(t.exception())[:400], flush=True), os._exit(3)) if not t.cancelled() and t.exception() else None)
    await asyncio.sleep(.5)
    t = "Toshkentdan Samarqandga taksi kerak 2 kishi +998901234567 soat 18:30"

    await step(msg("/id")); r = new()
    check("/id guruhda javob beradi", r and "-100111" in r[0][1], r)
    await step(msg("/stats")); r = new()
    check("/stats admin guruhda", r and "seen" in r[0][1], r)
    await step(msg("/stats", user=U(STRANGER))); check("/stats begona: jim", not new())

    await step(msg(t)); check("ro'yxatda yo'q guruh e'tiborsiz", not new())
    await step(msg("/add", user=U(STRANGER))); check("begona /add ishlamaydi", not new() and not store.find(-100111))
    await step(msg("/add")); r = new()
    check("admin /add", r and "qo'shildi" in r[0][1] and store.find(-100111), r)

    await step(msg("/addgroup @yangi https://t.me/ikkinchi2 @nope @notmember t.me/+inv", chat=PRIV())); r = new()
    print("   ", repr(r[0][1]) if r else r, flush=True)
    check("/addgroup bir nechta, xatolar aniq", r and store.find(-100333) and "❌ @nope: topilmadi" in r[0][1]
          and "a'zo emas" in r[0][1] and "❌ t.me/+inv" in r[0][1], r)
    await step(msg("/addgroup @yangi", chat=PRIV(STRANGER), user=U(STRANGER))); check("begona /addgroup jim", not new())
    await step(msg("/groups", chat=PRIV())); r = new()
    print("   ", repr(r[0][1]) if r else r, flush=True)
    check("/groups ro'yxat", r and "Yangi guruh" in r[0][1], r)

    gmsg = {**CBM, "message_id": 778, "chat": PRIV(), "text": "x"}
    answers.clear()
    await step(cbq(1, U(STRANGER), "gdel:-100333", gmsg))
    check("begona o'chira olmaydi", store.find(-100333) and len(answers) == 1 and answers[0].startswith("Faqat adminlar uchun"), answers)
    await step(cbq(2, U(ADMIN), "gdel:-100333", gmsg))
    check("admin tugma bilan o'chiradi", not store.find(-100333), store.all_groups())
    await step(msg("/delgroup -100111", chat=PRIV())); new()
    check("/delgroup", not store.find(-100111))
    store.add(-100111, None, "G")

    await step(joined(G(-100500), U(ADMIN))); check("admin qo'shsa avtomatik", store.find(-100500))
    await step(joined(G(-100600), U(STRANGER))); r = new()
    check("begona qo'shsa kuzatilmaydi, tasdiq so'raladi", r and "Kuzatish" not in "x" and not store.find(-100600), r)
    answers.clear()
    await step(cbq(3, U(STRANGER), "gadd:-100600", gmsg))
    check("tasdiqni begona bosa olmaydi", not store.find(-100600))
    await step(cbq(4, U(ADMIN), "gadd:-100600", gmsg)); check("admin tasdiqlaydi", store.find(-100600))
    await step({"message": {"message_id": 5, "date": int(time.time()), "chat": {"id": -600, "type": "group", "title": "x"},
                            "from": U(1), "migrate_to_chat_id": -100700}})
    store.add(-601, None, "eski")
    await step({"message": {"message_id": 5, "date": int(time.time()), "chat": {"id": -601, "type": "group", "title": "x"},
                            "from": U(1), "migrate_to_chat_id": -100701}})
    check("supergroup migratsiya", store.find(-100701) and not store.find(-601))

    new()
    await step(msg(t)); r = new()
    check("yo'lovchi e'lon qilinadi", len(r) == 1 and r[0][0] in ("-1009999", -1009999) and "Toshkent → Samarqand" in r[0][1], r)
    await step(msg(t, chat=G(-100500))); check("dedup boshqa guruhda", not new())
    await step(msg("Nukusdan Xivaga taksi kerak", user=U(5), age=3600)); check("1 soat oldingi xabar o'tkazib yuboriladi", not new())
    await step(msg("/help", chat=PRIV())); r = new(); check("/help admin yordam", r and "/addgroup" in r[0][1], r)
    await step(msg("/foo")); check("noma'lum buyruq e'tiborsiz", not new())

    fail.append(400)
    t2 = "Andijondan Namanganga taksi kerak +998911112233"
    await step(msg(t2, user=U(6))); new()
    await step(msg(t2, user=U(6))); r = new()
    check("400 xatodan keyin qayta yozilsa yetadi", len(r) == 1 and r[0][0] != "FAILED-400", r)
    fail.append(500)
    await step(msg("Termizdan Denovga taksi kerak +998931112233", user=U(7)))
    await asyncio.sleep(2.5); r = new()
    check("500 xatoda o'zi qayta yuboradi", len(r) == 2 and r[0][0] == "FAILED-500" and "FAILED" not in str(r[1][0]), r)

    await step(msg("Buxoroga taksi kerak", user=U(8))); new()
    await step(msg("Buxoroga yana taksi kerak, boshqa odam uchun", user=U(8))); r = new()
    check("to'liq bo'lmagan marshrut, boshqa matn: dublikat emas", len(r) == 1, r)
    await step(msg("Qarshidan Termizga taksi kerak +998941112233 2 kishi", user=U(9))); new()
    await step(msg("Qarshidan Termizga mashina kerak 2 kishi +998941112233", user=U(9))); check("to'liq marshrut, boshqa so'z: dublikat", not new())

    c0 = ai_calls[0]
    await step(msg("Salom hammaga")); await step(msg("Bugun havo yaxshi"))
    check("gap-so'z AI'ga bormaydi", ai_calls[0] == c0, ai_calls[0] - c0)
    await step(msg("Nukus AI_GOOD", user=U(10))); await asyncio.sleep(.4); r = new()
    check("AI natijasi, kirill shahar nomi kanonik", len(r) == 1 and "Nukus → Xiva" in r[0][1], r)
    await step(msg("Nukus AI_INT", user=U(11))); await asyncio.sleep(.4); r = new()
    check("AI from=123 yiqitmaydi", len(r) == 1 and "123" not in r[0][1].split("\n")[1], r)
    await step(msg("Nukus AI_LIST", user=U(12))); check("AI list yiqitmaydi", not new() and pipeline.stats["ai_errors"] == 1)
    await step(msg("Nukus AI_TAG", user=U(13))); r = new()
    check("AI seats=<x> e'lonni buzmaydi", len(r) == 1 and r[0][0] != "REJECTED", r)

    answers.clear(); edits.clear()
    # Haqiqiy poyga: ikkala bosish bir vaqtda ishlovga tushadi
    await step(cbq(10, U(21, "Vali")), cbq(11, U(22, "Soli")), cbq(12, U(22, "Soli")))
    print("    edits", edits, "\n    answers", answers, flush=True)
    check("Oldim: faqat bittasi oladi", len(edits) == 1 and answers.count("Siz oldingiz!") == 1
          and len(answers) == 3, (edits, answers))


    # ---------- Bot orqali buyurtma ----------
    P = 31
    pc, pu = PRIV(P), U(P, "Yolovchi")
    say = lambda t: step(msg(t, chat=pc, user=pu))
    def last():
        r = new()
        print("    <-", repr(r[-1][1][:110]) if r else r, flush=True)
        return r
    def contact(uid_):
        mid[0] += 1
        return {"message": {"message_id": mid[0], "date": int(time.time()), "chat": pc, "from": pu,
                            "contact": {"phone_number": "998951234567", "first_name": "Y", "user_id": uid_}}}
    await say("/start"); r = last()
    check("/start rol tanlash", r and "Siz kimsiz" in r[0][1] and "role:passenger" in markups[-1][1], (r, markups[-1:]))
    edits.clear()
    await step(cbq(39, pu, "role:passenger", {**CBM, "chat": pc, "message_id": 799}))
    check("yo'lovchi roli: buyurtma taklifi", any("Taksi kerakmi" in e[1] for e in edits), edits)
    await step(cbq(40, pu, "order:new", {**CBM, "chat": pc, "message_id": 800})); r = last()
    check("tugma: qayerdan", r and "Qayerdan" in r[-1][1], r)
    await say("1"); r = last(); check("noto'g'ri joy qayta so'raladi", r and "Joy nomini" in r[-1][1], r)
    await say("Sho'rchi tumani"); r = last(); check("qayerga", r and "Qayerga" in r[-1][1], r)
    await say("Sho'rchi tumani"); r = last(); check("bir xil joy rad etiladi", r and "bir xil" in r[-1][1], r)
    await say("Toshkentga"); r = last(); check("qachon", r and "Qachon" in r[-1][1], r)
    await say("ertaga 18:30"); r = last(); check("telefon so'raladi", r and "telefon" in r[-1][1], r)
    await say("salom"); r = last(); check("noto'g'ri raqam", r and "tushunilmadi" in r[-1][1], r)
    await step(contact(777)); r = last(); check("birovning kontakti rad", r and "o'zingizning" in r[-1][1], r)
    await step(contact(P)); r = last()
    check("tasdiqlash", r and "ertaga 18:30" in r[-1][1] and "+998 95 123 45 67" in r[-1][1] and "Sho" in r[-1][1], r)
    await say("/groups"); check("begona tasdiqda /groups jim", not new())
    await say("nimadir"); r = last(); check("tasdiqda matn: tugma eslatmasi", r and "tugmalardan" in r[-1][1], r)
    edits.clear(); stored.clear()
    conf = {**CBM, "chat": pc, "message_id": 801, "text": "x"}
    await step(cbq(41, pu, "order:send", conf), cbq(42, pu, "order:send", conf))
    await asyncio.sleep(.5); r = new()
    print("    group <-", repr(r[0][1]) if r else r, flush=True)
    orders = [x for x in r if "YANGI BUYURTMA" in x[1]]
    check("ikki bosishda bitta buyurtma guruhga", len(orders) == 1 and orders[0][0] in ("-1009999", -1009999), r)
    check("buyurtmada hamma ma'lumot", orders and all(k in orders[0][1] for k in ("Toshkent", "ertaga 18:30", "+998 95 123 45 67", "tg://user?id=31")), r)
    check("yo'lovchiga tasdiq", any("yuborildi" in e[1] for e in edits), edits)

    # ---------- 1-band: Yozish tugmasi ----------
    check("buyurtmada Yozish tugmasi", any("tg://user?id=31" in m[1] for m in markups), markups[-2:])
    new(); rejected.clear()
    await step(msg("Nukusdan Xivaga taksi kerak +998971112233", user=U(61))); await asyncio.sleep(.2); r = new()
    check("maxfiy yo'lovchi: e'lon tugmasiz yetadi", len(rejected) == 1 and len(r) == 1 and "Nukus" in r[0][1]
          and "tg://user?id=61" not in markups[-1][1] and "take" in markups[-1][1], (rejected, r, markups[-1:]))
    await step(msg("Xivadan Nukusga taksi kerak", user={**U(62), "username": "zzuser"})); await asyncio.sleep(.2); new()
    check("username bo'lsa t.me tugma", "https://t.me/zzuser" in markups[-1][1], markups[-1:])
    await step(msg("Urganchdan Nukusga taksi kerak", user=U(63))); await asyncio.sleep(.2); new()
    check("oddiy yo'lovchi: tg://user tugma", "tg://user?id=63" in markups[-1][1], markups[-1:])

    # ---------- 2-band: bot orqali yozishuv ----------
    D, D2 = 23, 24
    dc, du = PRIV(D), U(D, "Haydovchi")
    btn = [[{"text": "x", "url": "tg://user?id=31"}, {"text": "Oldim", "callback_data": f"take:{P}"}]]
    omsg = {**CBM, "message_id": 900, "text": "YANGI BUYURTMA\n📍 Sho'rchi → Toshkent\nX", "entities": [],
            "reply_markup": {"inline_keyboard": btn}}
    answers.clear(); stored.clear(); new()
    await step(cbq(43, du, f"take:{P}", omsg)); r = new()
    print("    take <-", [(x[0], x[1][:60]) for x in r], "\n    kb", last_edit.get("rm"), flush=True)
    check("Oldim: yo'lovchi xabardor", any(str(x[0]) == str(P) and "haydovchi oldi" in x[1] for x in r), r)
    check("Oldim: haydovchiga suhbat ochildi", any(str(x[0]) == str(D) and "suhbat ochildi" in x[1] for x in r), r)
    check("Oldimdan keyin bog'lanish tugmalari qoladi", "start=chat" in str(last_edit.get("rm"))
          and "tg://user?id=31" in str(last_edit.get("rm")) and "take" not in str(last_edit.get("rm")), last_edit)
    await step(msg("Salom, soat nechida?", chat=dc, user=du)); r = new()
    check("haydovchi -> yo'lovchi", len(r) == 1 and str(r[0][0]) == str(P) and "Haydovchi" in r[0][1] and "soat nechida" in r[0][1], r)
    await say("/start order"); new(); await say("/cancel"); new()
    await say("18:30 da"); r = new()
    check("yo'lovchi -> haydovchi (marshrut bilan)", len(r) == 1 and str(r[0][0]) == str(D) and "Toshkent" in r[0][1] and "18:30 da" in r[0][1], r)
    mid[0] += 1
    await step({"message": {"message_id": mid[0], "date": int(time.time()), "chat": pc, "from": pu,
                            "photo": [{"file_id": "a", "file_unique_id": "b", "width": 1, "height": 1}]}}); r = new()
    check("rasm copy_message bilan", copied and copied[-1] == (str(D), str(P), str(mid[0])) and len(r) == 1, (copied, r))

    # Boshqa haydovchi tugma bilan begona suhbatga kira olmaydi
    answers.clear()
    await step(cbq(47, U(25), f"relay:{P}", {**CBM, "chat": PRIV(25), "message_id": 950}))
    check("begona haydovchi suhbatga kira olmaydi", answers and "yopilgan" in answers[-1], answers)
    await step(msg("/start chat", chat=PRIV(25), user=U(25))); r = new()
    check("/start chat suhbatsiz", r and "ochiq suhbat" in r[-1][1], r)

    # Ikkinchi yo'lovchi: almashish
    R = 35
    rc, ru = PRIV(R), U(R, "R")
    om2 = {**CBM, "message_id": 901, "text": "YANGI BUYURTMA\n📍 Denov → Termiz", "entities": []}
    stored.clear()
    await step(cbq(48, du, f"take:{R}", om2)); new()
    await step(msg("Men ham salom", chat=dc, user=du)); r = new()
    check("yangi yo'lovchiga o'tdi", len(r) == 1 and str(r[0][0]) == str(R), r)
    await say("eski yo'lovchi yozdi"); r = new()
    check("eski yo'lovchidan almashish tugmasi bilan", str(r[0][0]) == str(D) and f"relay:{P}" in markups[-1][1], (r, markups[-1:]))
    await step(cbq(49, du, f"relay:{P}", {**CBM, "chat": dc, "message_id": 951}))
    await step(msg("Sizga javob", chat=dc, user=du)); r = new()
    check("almashgach eski yo'lovchiga boradi", len(r) == 1 and str(r[0][0]) == str(P), r)
    await step(msg("/chats", chat=dc, user=du)); r = new(); check("/chats ikkita", len(r) == 2, r)

    # /end: faqat tegishli suhbat yopiladi
    await step(msg("/end", chat=rc, user=ru)); r = new()
    check("yo'lovchi /end: haydovchi xabardor", any(str(x[0]) == str(D) and "yakunlandi" in x[1] for x in r), r)
    await step(msg("Oxirgi", chat=dc, user=du)); r = new()
    check("qolgan suhbat ishlaydi", len(r) == 1 and str(r[0][0]) == str(P), r)
    # Suhbat paytida yangi buyurtma: relay ga ketmaydi
    await say("/order"); r = new(); await say("Denov"); r = new()
    check("buyurtma to'ldirish suhbatga aralashmaydi", r and str(r[-1][0]) == str(P) and "Qayerga" in r[-1][1], r)
    await say("/cancel"); new()
    await step(msg("/end", chat=dc, user=du)); r = new()
    check("haydovchi /end: yo'lovchi xabardor", any(str(x[0]) == str(P) and "yakunlandi" in x[1] for x in r), r)
    await step(msg("Hali bormisiz", chat=dc, user=du)); r = new()
    check("yopilgach haydovchi matni relay ga bormaydi", not any(str(x[0]) == str(P) for x in r), r)

    # Haydovchi botni ochmagan
    W = 36
    answers.clear(); ans_urls.clear(); stored.clear()
    om3 = {**CBM, "message_id": 902, "text": "YANGI BUYURTMA\n📍 Qarshi → Toshkent", "entities": []}
    await step(cbq(50, U(D2, "Yangi"), f"take:{W}", om3)); new()
    check("botni ochmagan haydovchiga deep link", ans_urls and ans_urls[-1] and "start=chat" in ans_urls[-1], ans_urls)
    BLOCKED.discard(D2)
    await step(msg("/start chat", chat=PRIV(D2), user=U(D2))); r = new()
    check("deep link suhbatni ochadi", r and "suhbat ochildi" in r[-1][1], r)
    # Yo'lovchi botni bloklagan
    BLOCKED.add(W)
    await step(msg("Salom", chat=PRIV(D2), user=U(D2))); r = new()
    check("bloklagan yo'lovchi: aniq xabar, suhbat yopiladi", r and "bloklagan" in r[-1][1], r)
    BLOCKED.discard(W)

    # Birdan to'liq yozish; cooldown
    await say("Toshkentdan Denovga bugun 20:00 +998901112233"); r = last()
    check("to'liq matn darhol tasdiqqa", r and "Denov" in r[-1][1] and "tekshiring" in r[-1][1], r)
    answers.clear()
    await step(cbq(44, pu, "order:send", conf));
    check("cooldown ishlaydi", answers and "soniyadan" in str(answers[-1]) and not [x for x in new() if "YANGI" in x[1]], answers)
    await say("/cancel"); r = last(); check("/cancel", r and "Bekor" in r[-1][1], r)
    answers.clear()
    await step(cbq(45, pu, "order:send", conf)); check("eskirgan tasdiq", answers and "eskirgan" in str(answers[-1]), answers)
    await say("salom"); r = last(); check("oddiy matn: tugma taklifi", r and "tugmani" in r[-1][1], r)

    # Yuborish yiqilsa yo'lovchi biladi va cooldown yechiladi
    Q = 32
    qc, qu = PRIV(Q), U(Q, "Q")
    await step(msg("Termizdan Toshkentga ertaga +998901119988", chat=qc, user=qu)); new()
    fail.append(400); edits.clear(); stored.clear()
    await step(cbq(46, qu, "order:send", {**conf, "chat": qc})); await asyncio.sleep(.3); new()
    check("xato bo'lsa yo'lovchi biladi", any("Yuborib bo'lmadi" in e[1] for e in edits), edits)

    import config as _c; _c.OFFER_IN_GROUPS = True
    await step(msg("Qashqadaryoga taksi kerak", user=U(33))); r = new()
    check("guruhda taklif chiqadi", any("Bot orqali buyurtma" in x[1] for x in r), r)
    await step(msg("Yana taksi kerak", user=U(33))); r = new()
    check("taklif kuniga 1 marta", not any("Bot orqali buyurtma" in x[1] for x in r), r)
    await step(msg("/start order", chat=PRIV(34), user=U(34))); r = new()
    check("deep link darhol boshlaydi", r and "Qayerdan" in r[-1][1], r)

    # ---------- Guruh moderatsiyasi ----------
    import moderation as md
    md.WARN_TTL = 0.1
    _c.OFFER_IN_GROUPS = False
    def gm(text, user, **extra):
        x = msg(text, user=user)
        x["message"].update(extra)
        return x
    def was_deleted(x):
        return ("-100111", str(x["message"]["message_id"])) in deleted
    check("bot qo'shilganda guruhga salom va ogohlantirish", any(str(c) == "-100500" and "/settings" in t
          and "haydovchilar" in t for c, t in sent), sent[-3:])

    j = {"message": {"message_id": 5000, "date": int(time.time()), "chat": G(), "from": U(71),
                     "new_chat_members": [U(71)]}}
    await step(j); check("kirdi xabari o'chadi", ("-100111", "5000") in deleted, deleted)

    new()
    ad = gm("Zo'r kanal https://example.com", U(72))
    await step(ad); await asyncio.sleep(.3); r = new()
    check("reklama o'chadi, e'lon qilinmaydi, ogohlantirish chiqadi", was_deleted(ad)
          and len(r) == 1 and "reklama" in r[0][1] and str(r[0][0]) == "-100111", r)
    check("ogohlantirish keyin o'chadi", any(x[0] == "-100111" and int(x[1]) > 500 for x in deleted), deleted[-3:])
    ad2 = gm("yana https://example.com", U(72))
    await step(ad2); check("qayta reklama: o'chadi, ogohlantirish takrorlanmaydi", was_deleted(ad2) and not new())

    adm = gm("Admin havolasi https://example.com", U(ADMIN))
    await step(adm); check("admin havolasi qoladi", not was_deleted(adm), deleted[-2:])

    own = "Samarqanddan Jizzaxga taksi kerak, yozing @yolovchi77"
    ok_msg = gm(own, {**U(73), "username": "yolovchi77"}, entities=[ent_(own, "@yolovchi77")])
    await step(ok_msg); await asyncio.sleep(.2); r = new()
    check("o'z @username bilan yo'lovchi e'lon qilinadi", not was_deleted(ok_msg) and any("Samarqand" in x[1] for x in r), r)
    other = "Obuna bo'ling @zor_kanal"
    om = gm(other, U(74), entities=[ent_(other, "@zor_kanal")])
    await step(om); new(); check("begona @kanal o'chadi", was_deleted(om))
    fwd = gm("Chegirma!", U(75), forward_origin={"type": "channel", "chat": {"id": -100777, "type": "channel",
                                                   "title": "K"}, "message_id": 1, "date": 1})
    await step(fwd); new(); check("kanaldan forward o'chadi", was_deleted(fwd))
    mid[0] += 1
    ed = {"edited_message": {"message_id": mid[0], "date": int(time.time()), "edit_date": int(time.time()),
                             "chat": G(), "from": U(76), "text": "tahrir: t.me/reklama"}}
    await step(ed); new(); check("tahrirlab qo'shilgan havola o'chadi", ("-100111", str(mid[0])) in deleted)

    fl = [gm(f"salom {i}", U(77)) for i in range(7)]
    await step(*fl); await asyncio.sleep(.2); r = new()
    check("flood: 6-xabardan o'chadi va cheklanadi", not was_deleted(fl[4]) and was_deleted(fl[5]) and was_deleted(fl[6])
          and restricted.count(("-100111", "77")) == 1 and any("ketma-ket" in x[1] for x in r), (restricted, r))

    await step(msg("/settings", user=U(STRANGER))); check("/settings begona: jim", not new())
    await step(msg("/settings")); r = new()
    check("/settings admin: holat, hisob, admin qilish eslatmasi", r and "reklama 5" in r[0][1]
          and "kirdi-chiqdi 1" in r[0][1] and "admin qiling" in r[0][1], r)
    smsg = {**CBM, "message_id": 990, "chat": G(), "text": "x"}
    answers.clear()
    await step(cbq(60, U(STRANGER), "mod:ads", smsg))
    check("begona sozlamani o'zgartira olmaydi", md.settings(-100111)["ads"] and "Faqat" in str(answers), answers)
    await step(cbq(61, U(ADMIN), "mod:ads", smsg))
    check("admin reklama filtrini o'chiradi", not md.settings(-100111)["ads"] and "o‘chirildi" in str(answers[-1]), answers)
    ad3 = gm("endi mumkin https://example.com", U(78))
    await step(ad3); new(); check("filtr o'chiq: havola qoladi", not was_deleted(ad3))

    # ---------- Kanal va tugmali panel ----------
    PV = PRIV()
    def pcb(data, mid_=950):
        return cbq(uid[0] + 1, U(ADMIN), data, {**CBM, "chat": PV, "message_id": mid_})
    new()
    await step(msg("/menu", chat=PV, user=U(ADMIN)))
    check("panel: /menu tugmalar bilan", markups and "startgroup" in markups[-1][1] and "startchannel" in markups[-1][1]
          and "w:add_link" in markups[-1][1], markups[-1:])
    new()
    await step(msg("/menu", chat=PV, user=U(STRANGER))); check("begona /menu jim", not new())

    await step(pcb("w:add_link"))
    await step(msg("@taksi_kanal", chat=PV, user=U(ADMIN))); r = new()
    g = store.find(-100222)
    check("panel: havola bilan kanal qo'shiladi", g and store.kind_of(g) == "channel"
          and any("Kanal" in x[1] and "qo'shildi" in x[1] for x in r), (r, g))

    # Kanal posti haydovchilar guruhiga yetadi
    mid[0] += 1
    await step({"channel_post": {"message_id": mid[0], "date": int(time.time()),
                                 "chat": {"id": -100222, "type": "channel", "title": "Taksi Kanal",
                                          "username": "taksi_kanal"},
                                 "text": "Denovdan Toshkentga ketaman 3 kishi +998900000011"}}); r = new()
    check("kanal posti e'lon qilinadi", any(str(x[0]) == "-1009999" and "Denov" in x[1] for x in r), r)

    # Forward bilan qo'shish (guruh manbadan)
    await step(pcb("w:add_link"))
    mid[0] += 1
    await step({"message": {"message_id": mid[0], "date": int(time.time()), "chat": PV, "from": U(ADMIN),
                            "text": "manba", "forward_origin": {"type": "channel", "date": int(time.time()),
                            "chat": {"id": -100223, "type": "channel", "title": "Begona Kanal"}, "message_id": 7}}})
    r = new()
    check("forward: bot admin bo'lmagan kanalga aniq xato", any("ADMIN qiling" in x[1] for x in r)
          and not store.find(-100223), r)

    # Bot kanalga admin qilib qo'shilsa avtomatik kuzatuvga
    await step({"my_chat_member": {"chat": {"id": -100556, "type": "channel", "title": "Mening kanal"},
                                   "from": U(ADMIN), "date": int(time.time()),
                                   "old_chat_member": {"status": "left", "user": U(99)},
                                   "new_chat_member": ADMIN_CM}})
    check("bot kanalga admin qo'shilsa avtomatik kuzatuvga", store.find(-100556)
          and store.kind_of(store.find(-100556)) == "channel", store.all_groups())

    await step(pcb("w:list")); r = new()
    check("panel: ro'yxatda kanal belgisi bilan", any("📢" in x[1] and "Taksi Kanal" in x[1] for x in r), r)

    # ---------- Yo'nalish filtri + hashtag ----------
    import routes as _routes
    _routes.add("Termiz", "Toshkent")
    new()
    await step(msg("Termizdan Toshkentga ketaman 2 kishi +998900000022", user=U(80))); r = new()
    check("xizmat yo'nalishi: e'lon o'tadi va hashtag qo'yiladi",
          any(str(x[0]) == "-1009999" and "#Termiz_Toshkent" in x[1] for x in r), r)
    await step(msg("Samarqanddan Buxoroga ketaman 2 kishi +998900000033", user=U(81)))
    check("xizmatsiz yo'nalish: maxfiy guruhga tushmaydi", not [x for x in new() if str(x[0]) == "-1009999"])
    _routes.remove("Termiz", "Toshkent")

    # ---------- Haydovchi kabineti: akkaunt ulash, guruhlar, rassilka (soxta Telethon) ----------
    from types import SimpleNamespace
    from database import crud as _crud
    from handlers import driver_cabinet as dc
    from services import crypto as _crypto
    from services import userbot_auth as _auth
    from services.broadcaster import manager as _mgr

    class SessionPasswordNeededError(Exception):
        pass

    class PasswordHashInvalidError(Exception):
        pass

    class ChatWriteForbiddenError(Exception):
        pass

    class FakeClient:
        def __init__(self):
            self.sent, self.logged_out, self.connected, self.handlers = [], False, False, []
            self.session = SimpleNamespace(save=lambda: "SESSION-STR")

        async def connect(self):
            self.connected = True

        def is_connected(self):
            return self.connected

        async def is_user_authorized(self):
            return True

        async def send_code_request(self, phone):
            self.phone = phone
            return SimpleNamespace(phone_code_hash="h")

        async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
            if code is not None:
                self.code = code
                raise SessionPasswordNeededError()
            if password != "pw":
                raise PasswordHashInvalidError()

        async def get_me(self):
            return SimpleNamespace(id=555, username="drv", first_name="Ali", last_name=None)

        def add_event_handler(self, h, ev):
            self.handlers.append(h)

        async def iter_dialogs(self):
            for i, t in ((-100801, "Termiz Toshkent Taksi"), (-100802, "Denov taksi"), (-1009999, "Yopiq guruh")):
                yield SimpleNamespace(id=i, title=t, is_group=True)

        async def send_message(self, chat_id, text, **kw):
            self.kw = kw
            if chat_id == -100802:
                raise ChatWriteForbiddenError()
            self.sent.append((chat_id, text))

        async def log_out(self):
            self.logged_out = True

        async def disconnect(self):
            self.connected = False

    fc = FakeClient()
    _auth.client_factory = lambda: fc
    _mgr.sleep = lambda s: asyncio.sleep(min(s, 0.05))
    DRV = 70
    DV = PRIV(DRV)

    def dcb(data, mid_=970):
        return cbq(uid[0] + 1, U(DRV, "Haydovchi"), data, {**CBM, "chat": DV, "message_id": mid_})

    def acb(data, mid_=980):
        return cbq(uid[0] + 1, U(ADMIN), data, {**CBM, "chat": PRIV(), "message_id": mid_})

    new()
    await step(dcb("role:driver")); r = new()
    check("haydovchi roli kabinetni ochadi", r and "Haydovchi kabineti" in r[-1][1]
          and "Akkauntni ulash" in json.loads(markups[-1][1])["keyboard"][0][0]["text"], (r, markups[-1:]))
    await step(msg(dc.BTN_CONNECT, chat=DV, user=U(DRV))); r = new()
    check("ulash: telefon so'raladi", r and "telefon" in r[-1][1], r)
    await step(msg("+998 90 111 22 33", chat=DV, user=U(DRV))); r = new()
    check("kod so'raladi: raqamli klaviatura chiqadi",
          fc.phone == "+998901112233" and r and "Kodni pastdagi tugmalar" in r[-1][1]
          and "dc:k:ok" in markups[-1][1], (getattr(fc, "phone", None), r))
    deleted.clear()
    await step(msg("1 2 3 4 5", chat=DV, user=U(DRV))); r = new()
    check("kod qabul qilindi, chatdan o'chirildi, 2FA so'raladi",
          fc.code == "12345" and deleted and r and "2FA" in r[-1][1], (deleted, r))
    await step(msg("xato", chat=DV, user=U(DRV))); r = new()
    check("noto'g'ri parol", r and "Noto'g'ri" in r[-1][1], r)
    await step(msg("pw", chat=DV, user=U(DRV))); r = new()
    row = _crud.get_session(DRV)
    check("akkaunt ulandi, sessiya shifrlangan holda saqlandi",
          row and row["session_enc"] != "SESSION-STR" and _crypto.decrypt(row["session_enc"]) == "SESSION-STR"
          and _mgr.is_connected(DRV) and any("Akkaunt ulandi" in x[1] for x in r), (row and dict(row), r))

    await step(msg(dc.BTN_GROUPS, chat=DV, user=U(DRV))); r = new()
    check("guruhlar sahifalangan ro'yxatda, yopiq guruh chiqmaydi",
          r and "Guruhlarni tanlang" in r[-1][1] and "dc:g:-100801" in markups[-1][1]
          and "-1009999" not in markups[-1][1], (r, markups[-1:]))
    await step(dcb("dc:g:-100801:0"))
    _crud.set_setting("max_groups", 1)
    answers.clear()
    await step(dcb("dc:g:-100802:0"))
    check("maks. guruh limiti", answers and "Ko'pi bilan 1" in (answers[-1] or "")
          and len(_crud.selected_groups(DRV)) == 1, answers)
    _crud.set_setting("max_groups", 12)
    await step(dcb("dc:g:-100802:0"))
    check("ikki guruh tanlandi va o'qish keshiga tushdi",
          len(_crud.selected_groups(DRV)) == 2 and _mgr.selected[DRV] == {-100801, -100802}, _mgr.selected)

    # Guruhlarni nomi bo'yicha qidirish (kirillcha yozilsa ham lotin nom topiladi)
    await step(dcb("dc:search")); new()
    await step(msg("денов", chat=DV, user=U(DRV))); r = new()
    check("qidiruv: faqat mos guruh chiqadi", r and "1 ta topildi" in r[-1][1] and "dc:g:-100802" in markups[-1][1]
          and "dc:g:-100801" not in markups[-1][1] and "dc:sclear" in markups[-1][1], (r, markups[-1:]))
    await step(dcb("dc:g:-100802:0"))
    check("qidiruv ichida tanlash ishlaydi, filtr saqlanadi", len(_crud.selected_groups(DRV)) == 1
          and "1 ta topildi" in stored.get("t", ""), stored.get("t"))
    await step(dcb("dc:g:-100802:0"))
    await step(dcb("dc:search")); new()
    await step(msg("yo'q guruh", chat=DV, user=U(DRV))); r = new()
    check("qidiruv: topilmadi xabari", r and "topilmadi" in r[-1][1], r)
    await step(dcb("dc:sclear"))
    check("qidiruv tozalandi: hamma guruh", "topildi" not in stored.get("t", "x") and "Guruhlarni tanlang" in stored.get("t", ""),
          stored.get("t"))

    await step(msg(dc.BTN_TEXT, chat=DV, user=U(DRV))); new()
    await step(msg("termizdan toshkentga bugun 18:00 da chiqamiz 3 joy bor oldi bo'sh +998901112233",
                   chat=DV, user=U(DRV))); r = new()
    check("e'lon formatlanib, tasdiqlash so'raldi", any("TERMIZ ➜ TOSHKENT" in x[1] and "+998 90 111 22 33" in x[1]
                                                        and "Oldi o'rindiq" in x[1] for x in r)
          and "dc:ad:pretty" in markups[-1][1], r)
    await step(dcb("dc:ad:pretty"))
    ad = _crud.get_session(DRV)["ad_text"]
    check("formatlangan e'lon saqlandi", ad.startswith("🚕 TERMIZ ➜ TOSHKENT") and "💺 3 ta bo'sh joy" in ad
          and "🕕 Bugun 18:00" in ad, ad)
    await step(msg(dc.BTN_TEXT, chat=DV, user=U(DRV))); new()
    await step(msg("Termiz → Toshkent, bugun 18:00, 3 joy bor", chat=DV, user=U(DRV))); new()
    await step(dcb("dc:ad:raw"))
    check("asl matn tanlansa o'zgarishsiz saqlanadi", _crud.get_session(DRV)["ad_text"] == "Termiz → Toshkent, bugun 18:00, 3 joy bor")
    await step(msg(dc.BTN_START, chat=DV, user=U(DRV))); r = new()
    check("ruxsatsiz rassilka yoqilmaydi, admin bilan bog'lanish tugmasi", r and "ruxsat" in r[-1][1]
          and not _mgr.is_running(DRV) and "https://t.me/admin_jasur" in markups[-1][1], (r, markups[-1:]))

    # ---------- /admin ----------
    await step(msg("/admin", chat=PRIV(STRANGER), user=U(STRANGER))); check("begona /admin jim", not new())
    await step(msg("/admin", chat=PRIV(), user=U(ADMIN))); r = new()
    check("/admin panel", r and "Admin panel" in r[-1][1] and "ap:stats" in markups[-1][1], r)
    answers.clear()
    await step(cbq(uid[0] + 1, U(STRANGER), "ap:stats", {**CBM, "chat": PRIV(STRANGER)}))
    check("begona ap: tugmasi rad etiladi", answers and "Faqat adminlar" in (answers[-1] or ""), answers)
    await step(acb("ap:search")); new()
    await step(msg("70", chat=PRIV(), user=U(ADMIN))); r = new()
    check("haydovchi ID bo'yicha topildi", r and "ID: <code>70</code>" in r[-1][1] and "ap:sub:70:7" in markups[-1][1], r)
    await step(acb("ap:sub:70:7")); r = new()
    check("+7 kun ruxsat berildi va haydovchiga xabar", _crud.has_access(DRV)
          and any(str(x[0]) == "70" and "7 kunga" in x[1] for x in r), r)

    fc.sent.clear()
    await step(msg(dc.BTN_START, chat=DV, user=U(DRV)))
    kbs = [json.dumps(json.loads(m_[1]), ensure_ascii=False) for m_ in markups[-3:] if m_[1].startswith("{")]
    check("rassilka boshlandi, tugma «To'xtatish» ga almashdi",
          any("Rassilka boshlandi" in x[1] for x in sent[mark[0]:]) and _mgr.is_running(DRV)
          and any(dc.BTN_STOP in k for k in kbs), (sent[mark[0]:], kbs))
    await asyncio.sleep(.5); r = new()
    check("e'lon guruhga yuborildi, yozib bo'lmagan guruh tanlovdan chiqdi, haydovchi ogohlantirildi",
          any(c == -100801 for c, _ in fc.sent) and fc.kw.get("parse_mode", 1) is None and _crud.selected_groups(DRV) == [(-100801, "Termiz Toshkent Taksi")]
          and any(str(x[0]) == "70" and "tanlovdan chiqarildi" in x[1] for x in r), (fc.sent, r))

    # O'qish: haydovchi tanlagan guruhdagi yo'lovchi e'loni yopiq guruhga tushadi (bir marta)
    def ev(text, sender=777, mid_=1, chat=-100801):
        async def gs():
            return SimpleNamespace(first_name="Vali", last_name=None, username="vali", bot=False)

        async def gc():
            return SimpleNamespace(title="Termiz Toshkent Taksi", username="termiz_taksi")
        return SimpleNamespace(chat_id=chat, id=mid_, raw_text=text, sender_id=sender, is_group=True,
                               get_sender=gs, get_chat=gc)

    new()
    e1 = ev("Termizdan Toshkentga taksi kerak 2 kishi +998900000044", mid_=11)
    await fc.handlers[0](e1); await asyncio.sleep(.3); r = new()
    check("haydovchi guruhidan yo'lovchi e'loni yopiq guruhga tushdi",
          any(str(x[0]) == "-1009999" and "YO'LOVCHI" in x[1] and "termiz_taksi" in x[1] for x in r), r)
    await _mgr.on_message(DRV, e1); await asyncio.sleep(.2)
    check("bir xabar ikki marta ishlanmaydi", not new())
    await _mgr.on_message(DRV, ev("Toshkentga ketaman, kim bor? 4 joy bosh", mid_=12)); await asyncio.sleep(.2)
    check("haydovchi e'loni yopiq guruhga tushmaydi", not new())
    await _mgr.on_message(DRV, ev("Samarqandga taksi kerak", sender=555, mid_=13)); await asyncio.sleep(.2)
    check("ulangan akkauntning o'z xabari o'qilmaydi", not new())
    await _mgr.on_message(DRV, ev("Buxoroga taksi kerak", chat=-100999, mid_=14)); await asyncio.sleep(.2)
    check("tanlanmagan guruh o'qilmaydi", not new())

    await step(acb("ap:stats")); r = new() + [("edit", e[1]) for e in edits[-1:]]
    check("statistika: aktiv rassilka va sessiya", any("qilayotganlar: <b>1" in x[1] or "qilayotganlar: 1" in x[1]
                                                      for x in r) or "Statistika" in stored.get("t", ""), r)
    st = __import__("handlers.admin_panel", fromlist=["x"]).stats_text()
    check("statistika matni", "ulagan haydovchilar: <b>1</b>" in st and "qilayotganlar: <b>1</b>" in st, st)

    # Global Stop
    await step(acb("ap:gstop")); await step(acb("ap:gstop_do"))
    check("Global Stop hamma rassilkani to'xtatadi", not _mgr.is_running(DRV) and _crud.get_setting("global_stop")
          and not _crud.get_session(DRV)["is_running"])
    new()
    await step(msg(dc.BTN_START, chat=DV, user=U(DRV))); r = new()
    check("Global Stop paytida yoqib bo'lmaydi", r and "to'xtatgan" in r[-1][1] and not _mgr.is_running(DRV), r)
    await step(acb("ap:gstop"))
    check("Global Stop o'chirildi", not _crud.get_setting("global_stop"))

    # Smart Routing: yo'nalish -> yopiq guruh
    await step(acb("ap:radd")); new()
    await step(msg("Toshkent - Samarqand", chat=PRIV(), user=U(ADMIN))); r = new()
    check("yo'nalish nomi qabul qilindi, chat_id so'raladi", r and "chat_id" in r[-1][1], r)
    await step(msg("-100777", chat=PRIV(), user=U(ADMIN))); r = new()
    rs = _crud.all_routes()
    check("yo'nalish yopiq guruh bilan saqlandi", rs and rs[-1]["chat_id"] == -100777, [dict(x) for x in rs])
    await step(msg("Toshkentdan Samarqandga taksi kerak 1 kishi +998900000055", user=U(82))); r = new()
    check("e'lon yo'nalishning yopiq guruhiga tushdi", any(str(x[0]) == "-100777" for x in r)
          and not any(str(x[0]) == "-1009999" for x in r), r)
    await step(msg("Termizdan Toshkentga taksi kerak 1 kishi +998900000066", user=U(83)))
    check("ro'yxatda yo'q yo'nalish o'tmaydi", not [x for x in new() if str(x[0]).startswith("-100")])
    await step(acb(f"ap:rdel:{rs[-1]['id']}"))
    check("yo'nalish o'chirildi", not _crud.all_routes())

    # Bloklash
    await step(acb("ap:blk:70"))
    check("bloklandi", _crud.is_blocked(DRV)); new()
    await step(msg(dc.BTN_HELP, chat=DV, user=U(DRV))); r = new()
    check("bloklangan foydalanuvchi to'xtatiladi", r and "bloklangansiz" in r[-1][1], r)
    await step(acb("ap:blk:70"))
    check("blokdan chiqarildi", not _crud.is_blocked(DRV))

    # Umumiy xabarnoma
    copied.clear()
    await step(acb("ap:bcast")); new()
    await step(msg("Hurmatli foydalanuvchilar!", chat=PRIV(), user=U(ADMIN))); r = new()
    check("xabarnoma: auditoriya so'raladi", r and "Kimga" in r[-1][1] and "ap:bc:all" in markups[-1][1], r)
    await step(acb("ap:bc:driver")); await asyncio.sleep(.3); r = new()
    check("xabarnoma haydovchilarga yetdi", ("70", "1") == copied[0][:2] if copied else False, copied)

    # Akkauntni uzish
    await step(dcb("dc:logout_do"))
    check("akkaunt uzildi, sessiya o'chirildi", fc.logged_out and _crud.get_session(DRV) is None
          and not _mgr.is_connected(DRV))

    # ---------- Donor guruhlar (Parser) ----------
    from services import donor_parser as _dp

    def dev(text, mid_, entities=(), buttons=(), chat=-100500):
        rows = [SimpleNamespace(buttons=[SimpleNamespace(**b) for b in row]) for row in buttons]
        m_ = SimpleNamespace(message=text, entities=list(entities), id=mid_,
                             reply_markup=SimpleNamespace(rows=rows) if rows else None)

        async def gs():
            return SimpleNamespace(id=1, username="agg_bot", first_name="Agg", bot=True)
        return SimpleNamespace(chat_id=chat, id=mid_, message=m_, raw_text=text, sender_id=1, get_sender=gs)

    await step(acb("ap:donors"))
    check("admin: donor bo'limi", "Donor guruhlar (Parser)" in stored.get("t", "") and "Texnik userbot" in stored.get("t", ""),
          stored.get("t"))
    await step(acb("ap:dadd")); new()
    await step(msg("-1009999", chat=PRIV(), user=U(ADMIN))); r = new()
    check("yopiq guruhni donor qilib bo'lmaydi", r and "donor qilib bo'lmaydi" in r[-1][1], r)
    await step(msg("-100500", chat=PRIV(), user=U(ADMIN))); r = new()
    check("donor qo'shildi", r and "Qo'shildi" in r[-1][1] and _dp.is_donor(-100500) and "ap:dtgt:-100500" in markups[-1][1], r)

    t_ = "🚖 Denovdan Samarqand ketish qancha bo'lyapti\nКлиент личкаси\n📢 Kanalimizga obuna bo'ling @reklama"
    off = len(t_[:t_.index("Клиент")].encode("utf-16-le")) // 2
    ent = SimpleNamespace(offset=off, length=14, url="tg://user?id=5551234")
    res_ = await _dp.handle(dev(t_, 1, [ent])); await asyncio.sleep(.3); r = new()
    out = [x for x in r if str(x[0]) == "-1009999"]
    check("donor: mijoz yopiq guruhga yashirin havola va tugma bilan uzatildi",
          res_ == "sent" and out and "Yangi mijoz aniqlandi!" in out[-1][1] and "<code>5551234</code>" in out[-1][1]
          and 'href="tg://user?id=5551234"' in out[-1][1] and "obuna" not in out[-1][1]
          and "tg://user?id=5551234" in markups[-1][1] and "take" in markups[-1][1], (res_, r, markups[-1:]))
    check("donor: bir xil mijoz 30 daqiqada qayta uzatilmaydi",
          await _dp.handle(dev("Denovdan yana taksi kerak", 2,
                               buttons=[[{"text": "Lichka", "url": "tg://user?id=5551234"}]])) == "dup")
    check("donor: haydovchi e'loni uzatilmaydi",
          await _dp.handle(dev("Ertaga ertalab Toshkentga ketamz odam poshta olamz +998998269111", 3)) == "driver")
    hid = sorted(HIDDEN)[0]
    res_ = await _dp.handle(dev("Navoiyga taksi kerak 1 kishi", 4,
                                buttons=[[{"text": "Профиль", "url": f"tg://user?id={hid}"}]]))
    await asyncio.sleep(.3); r = new()
    check("donor: maxfiy profil tugmasi rad etilsa tugmasiz yuboriladi, «Oldim» qoladi",
          res_ == "sent" and any(str(x[0]) == "-1009999" and "Navoiy" in x[1] for x in r)
          and f"tg://user?id={hid}" not in markups[-1][1] and "take" in markups[-1][1], (r, markups[-1:]))

    await step(acb("ap:dtgt:-100500")); new()
    await step(msg("-100777", chat=PRIV(), user=U(ADMIN))); r = new()
    check("donor yopiq guruhga bog'landi", _crud.get_donor(-100500)["target_chat_id"] == -100777, r)
    await _dp.handle(dev("Qarshiga taksi kerak +998901234000", 5)); await asyncio.sleep(.3); r = new()
    check("donor mijozi bog'langan guruhga tushdi", any(str(x[0]) == "-100777" and "Qarshi" in x[1] for x in r), r)
    await step(acb("ap:dtog:-100500"))
    check("donor to'xtatildi", not _dp.is_donor(-100500))
    await step(acb("ap:ddel:-100500"))
    check("donor o'chirildi", _crud.get_donor(-100500) is None)
    st = __import__("handlers.admin_panel", fromlist=["x"]).stats_text()
    check("statistikada donor", "Donor: uzatildi 3" in st, st)

    print("\n/stats:", pipeline.stats, flush=True)
    pending.clear()
    for o in __import__("gc").get_objects():
        from aiogram import Dispatcher
        if isinstance(o, Dispatcher) and o._running_lock.locked():
            await o.stop_polling()
            break
    try:
        await asyncio.wait_for(asyncio.shield(task), 5)
        check("polling to'xtasa main() tugaydi", True)
    except asyncio.TimeoutError:
        check("polling to'xtasa main() tugaydi", False)
    print(f"\n{sum(passed)}/{len(passed)} o'tdi", flush=True)
    print("groups.json:", (tmp / "groups.json").read_text(encoding="utf-8")[:200].replace("\n", " "), flush=True)
    os._exit(0 if all(passed) else 1)


asyncio.run(run())
