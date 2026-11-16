"""/admin — yopiq boshqaruv paneli (faqat ADMIN_IDS).

Bo'limlar:
  1. 📊 Statistika va monitoring
  2. 👥 Haydovchilar: qidirish, obuna (+7/+30 kun, cheksiz), blok, sessiyani uzish, rassilkani to'xtatish
  3. 🗂 Yo'nalishlar va yopiq guruhlar (Smart Routing)
  4. ⚙️ Tizim sozlamalari: maks. guruhlar, minimal pauza, minimal interval, 🚨 Global Stop
  5. 📢 Umumiy xabarnoma (matn/rasm/video) — hammaga, haydovchilarga yoki yo'lovchilarga
Callback prefiksi: "ap:".
"""
import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import pipeline
import routes
from database import crud
from nlp import canon_city, known_city
from services.broadcaster import manager

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
B = InlineKeyboardButton
BROADCAST_DELAY = 0.05          # ~20 xabar/soniya — Telegram limitidan past


class Adm(StatesGroup):
    search = State()
    route_name = State()
    route_chat = State()
    route_edit_chat = State()
    setting = State()
    bcast = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


BACK = B(text="⬅️ Orqaga", callback_data="ap:menu")


def _main_kb():
    return _kb(
        [B(text="📊 Statistika", callback_data="ap:stats")],
        [B(text="👥 Haydovchilar va ruxsatlar", callback_data="ap:drivers")],
        [B(text="🗂 Yo'nalishlar va yopiq guruhlar", callback_data="ap:routes")],
        [B(text="⚙️ Tizim sozlamalari", callback_data="ap:settings")],
        [B(text="📢 Umumiy xabarnoma", callback_data="ap:bcast")],
    )


MAIN_TEXT = "🛠 <b>Admin panel</b>\nBo'limni tanlang:"


async def _show(cb: CallbackQuery, text: str, kb):
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except TelegramAPIError:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


@router.message(Command("admin"))
async def on_admin(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return                      # begonaga panel borligini ham bildirmaymiz
    await state.clear()
    await msg.answer(MAIN_TEXT, parse_mode="HTML", reply_markup=_main_kb())


# Barcha ap:* callbacklar uchun umumiy tekshiruv
@router.callback_query(F.data.startswith("ap:"), lambda cb: not is_admin(cb.from_user.id))
async def on_not_admin(cb: CallbackQuery):
    await cb.answer("Faqat adminlar uchun", show_alert=True)


@router.callback_query(F.data == "ap:menu")
async def on_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show(cb, MAIN_TEXT, _main_kb())
    await cb.answer()


@router.message(StateFilter(Adm), Command("cancel"))
async def on_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(MAIN_TEXT, parse_mode="HTML", reply_markup=_main_kb())


# ================= 1. Statistika =================
def stats_text() -> str:
    c = crud.counts()
    s = pipeline.stats
    stop = "🚨 YOQILGAN" if crud.get_setting("global_stop") else "o'chiq"
    return (
        "📊 <b>Statistika</b>\n\n"
        f"👤 Jami foydalanuvchilar: <b>{c['users']}</b>\n"
        f"   🚕 haydovchi: {c['drivers']} · 🧍 yo'lovchi: {c['passengers']} · 🚫 blokda: {c['blocked']}\n"
        f"🔐 Akkaunt ulagan haydovchilar: <b>{c['sessions']}</b> (hozir onlayn: {manager.connected_count()})\n"
        f"🚀 Hozir rassilka qilayotganlar: <b>{manager.running_count()}</b>\n"
        f"💳 Amaldagi obunalar: {c['subscribed']}\n"
        f"📤 24 soatda tarqatilgan e'lonlar: {c['posts_24h']}\n"
        f"🚨 Global Stop: {stop}\n\n"
        f"<b>Yo'lovchi e'lonlari (restartdan beri)</b>\n"
        f"ko'rildi: {s['seen']} · yo'lovchi: {s['passenger']} · haydovchi: {s['driver']}\n"
        f"yuborildi: {s['sent']} · dublikat: {s['dup']} · xato: {s['failed']} · buyurtma: {s['orders']}"
    )


@router.callback_query(F.data == "ap:stats")
async def on_stats(cb: CallbackQuery):
    await _show(cb, stats_text(), _kb([B(text="🔄 Yangilash", callback_data="ap:stats")], [BACK]))
    await cb.answer()


# ================= 2. Haydovchilar =================
def _drivers_list_kb():
    rows = []
    for s in crud.all_sessions()[:40]:
        uid = s["user_id"]
        mark = "🚀" if manager.is_running(uid) else ("🟢" if manager.is_connected(uid) else "⚪️")
        name = s["tg_name"] or str(uid)
        rows.append([B(text=f"{mark} {name[:30]}", callback_data=f"ap:u:{uid}")])
    rows.append([B(text="🔎 ID / @username bo'yicha qidirish", callback_data="ap:search")])
    rows.append([BACK])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "ap:drivers")
async def on_drivers(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    n = len(crud.all_sessions())
    await _show(cb, f"👥 <b>Akkaunt ulagan haydovchilar: {n}</b>\n🚀 rassilkada · 🟢 onlayn · ⚪️ oflayn\n\n"
                    "Profilni ochish uchun bosing yoki qidiring.", _drivers_list_kb())
    await cb.answer()


@router.callback_query(F.data == "ap:search")
async def on_search(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Adm.search)
    await cb.message.answer("Haydovchining Telegram ID raqami yoki @username ini yuboring. Bekor: /cancel")
    await cb.answer()


def profile(uid: int):
    u = crud.get_user(uid)
    s = crud.get_session(uid)
    if u is None:
        return None, None
    e = html.escape
    lines = [f"👤 <b>{e(u['full_name'] or '—')}</b>",
             f"ID: <code>{uid}</code>" + (f" · @{e(u['username'])}" if u["username"] else ""),
             f"Rol: {u['role'] or '—'}",
             f"Ruxsat: {crud.sub_text(u)}",
             f"Holat: {'🚫 BLOKLANGAN' if u['is_blocked'] else '✅ faol'}"]
    if s:
        lines += [f"\n🔐 Akkaunt: {e(s['tg_name'] or '')}" + (f" @{e(s['tg_username'])}" if s["tg_username"] else ""),
                  f"Onlayn: {'ha' if manager.is_connected(uid) else 'yoʻq'} · "
                  f"Rassilka: {'🚀 ishlayapti' if manager.is_running(uid) else 'toʻxtagan'}",
                  f"Tanlangan guruhlar: {len(crud.selected_groups(uid))} · interval: {s['interval_min']} daq"]
    else:
        lines.append("\n🔐 Akkaunt ulanmagan")
    rows = [
        [B(text="+7 kun", callback_data=f"ap:sub:{uid}:7"), B(text="+30 kun", callback_data=f"ap:sub:{uid}:30"),
         B(text="♾ Cheksiz", callback_data=f"ap:sub:{uid}:inf")],
        [B(text="❌ Ruxsatni olish", callback_data=f"ap:sub:{uid}:off")],
        [B(text="✅ Blokdan chiqarish" if u["is_blocked"] else "🚫 Bloklash", callback_data=f"ap:blk:{uid}")],
    ]
    if s:
        if manager.is_running(uid):
            rows.append([B(text="🛑 Rassilkani to'xtatish", callback_data=f"ap:stop:{uid}")])
        rows.append([B(text="🔌 Sessiyani uzish", callback_data=f"ap:kill:{uid}")])
    rows.append([B(text="🔄", callback_data=f"ap:u:{uid}"), B(text="⬅️ Ro'yxat", callback_data="ap:drivers")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(StateFilter(Adm.search))
async def on_search_input(msg: Message, state: FSMContext):
    u = crud.find_user(msg.text or "")
    if u is None:
        await msg.answer("❌ Topilmadi. Foydalanuvchi botga kamida bir marta /start bosgan bo'lishi kerak. "
                         "Qayta yuboring yoki /cancel")
        return
    await state.clear()
    text, kb = profile(u["user_id"])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("ap:u:"))
async def on_profile(cb: CallbackQuery):
    text, kb = profile(int(cb.data[5:]))
    if text is None:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await _show(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ap:sub:"))
async def on_sub(cb: CallbackQuery, bot: Bot):
    _, _, uid, what = cb.data.split(":")
    uid = int(uid)
    if what == "inf":
        crud.set_unlimited(uid, True)
        note = "♾ Sizga cheksiz rassilka ruxsati berildi."
    elif what == "off":
        crud.revoke_subscription(uid)
        manager.stop_broadcast(uid)
        note = "🔒 Rassilka ruxsatingiz olib qo'yildi."
    else:
        crud.add_subscription(uid, int(what))
        note = f"✅ Rassilka ruxsati {what} kunga uzaytirildi.\n{crud.sub_text(crud.get_user(uid))}"
    try:
        await bot.send_message(uid, note)
    except TelegramAPIError:
        pass
    text, kb = profile(uid)
    await _show(cb, text, kb)
    await cb.answer("Saqlandi")


@router.callback_query(F.data.startswith("ap:blk:"))
async def on_block(cb: CallbackQuery):
    uid = int(cb.data[7:])
    if is_admin(uid):
        await cb.answer("Adminni bloklab bo'lmaydi", show_alert=True)
        return
    blocked = not crud.is_blocked(uid)
    crud.set_blocked(uid, blocked)
    if blocked:
        manager.stop_broadcast(uid)
        await manager.notify(uid, "🚫 Siz admin tomonidan bloklandingiz. Rassilka to'xtatildi.")
    else:
        await manager.notify(uid, "✅ Blokdan chiqarildingiz.")
    text, kb = profile(uid)
    await _show(cb, text, kb)
    await cb.answer("Bloklandi" if blocked else "Blokdan chiqarildi")


@router.callback_query(F.data.startswith("ap:stop:"))
async def on_force_stop(cb: CallbackQuery):
    uid = int(cb.data[8:])
    manager.stop_broadcast(uid)
    await manager.notify(uid, "🛑 Rassilkangiz admin tomonidan to'xtatildi.")
    text, kb = profile(uid)
    await _show(cb, text, kb)
    await cb.answer("To'xtatildi")


@router.callback_query(F.data.startswith("ap:kill:"))
async def on_kill(cb: CallbackQuery):
    uid = int(cb.data[8:])
    await _show(cb, "Sessiyani uzasizmi? Haydovchining akkaunti botdan chiqariladi (log out), "
                    "u qayta ulanishi kerak bo'ladi.",
                _kb([B(text="🔌 Ha, uzish", callback_data=f"ap:killdo:{uid}")],
                    [B(text="Bekor", callback_data=f"ap:u:{uid}")]))
    await cb.answer()


@router.callback_query(F.data.startswith("ap:killdo:"))
async def on_kill_do(cb: CallbackQuery):
    uid = int(cb.data[10:])
    await manager.disconnect(uid, logout=True)
    await manager.notify(uid, "🔌 Akkauntingiz admin tomonidan botdan uzildi.")
    text, kb = profile(uid)
    await _show(cb, text, kb)
    await cb.answer("Uzildi")


# ================= 3. Yo'nalishlar (Smart Routing) =================
def _route_label(r) -> str:
    target = html.escape(r["title"] or str(r["chat_id"])) if r["chat_id"] else "asosiy guruh (DRIVERS_CHAT_ID)"
    return f"{r['city_a']} ↔ {r['city_b']} → {target}"


def routes_view():
    rs = crud.all_routes()
    if not rs:
        head = ("🗂 <b>Yo'nalishlar</b>\n\nRo'yxat bo'sh — barcha yo'lovchi e'lonlari asosiy yopiq guruhga "
                "(DRIVERS_CHAT_ID) tushadi.\n\nYo'nalish qo'shsangiz, faqat o'shalar o'tadi va har biri o'z "
                "yopiq guruhiga yuboriladi.")
    else:
        head = "🗂 <b>Yo'nalishlar → yopiq guruhlar</b>\n\n" + "\n".join(
            f"{i}. {_route_label(r)}" for i, r in enumerate(rs, 1))
        head += f"\n\nYo'nalishi aniqlanmagan e'lonlar: {'tashlanadi' if config.ROUTE_FILTER_STRICT else 'asosiy guruhga'}"
    kb = [[B(text=f"✏️ {r['city_a']} ↔ {r['city_b']}"[:60], callback_data=f"ap:r:{r['id']}")] for r in rs]
    kb.append([B(text="➕ Yangi yo'nalish", callback_data="ap:radd")])
    kb.append([BACK])
    return head, InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "ap:routes")
async def on_routes(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = routes_view()
    await _show(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ap:r:"))
async def on_route_card(cb: CallbackQuery):
    r = crud.get_route(int(cb.data[5:]))
    if r is None:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await _show(cb, f"🧭 <b>{_route_label(r)}</b>",
                _kb([B(text="✏️ Yopiq guruhni o'zgartirish", callback_data=f"ap:rchat:{r['id']}")],
                    [B(text="❌ O'chirish", callback_data=f"ap:rdel:{r['id']}")],
                    [B(text="⬅️ Yo'nalishlar", callback_data="ap:routes")]))
    await cb.answer()


@router.callback_query(F.data.startswith("ap:rdel:"))
async def on_route_del(cb: CallbackQuery):
    crud.delete_route(int(cb.data[8:]))
    text, kb = routes_view()
    await _show(cb, text, kb)
    await cb.answer("O'chirildi")


@router.callback_query(F.data == "ap:radd")
async def on_route_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Adm.route_name)
    await cb.message.answer("Yo'nalish nomini yuboring, masalan: <b>Toshkent - Samarqand</b>\nBekor: /cancel",
                            parse_mode="HTML")
    await cb.answer()


CHAT_PROMPT = ("Endi shu yo'nalish e'lonlari tushadigan <b>yopiq guruh</b>ni yuboring:\n"
               "• guruh <code>chat_id</code> si (masalan <code>-1001234567890</code>, guruhda /id yozib olinadi), yoki\n"
               "• o'sha guruhdan istalgan xabarni shu yerga <b>forward</b> qiling, yoki\n"
               "• <code>0</code> — asosiy guruhga (DRIVERS_CHAT_ID)\n\n"
               "Bot o'sha guruhga a'zo va yoza oladigan bo'lishi kerak. Bekor: /cancel")


@router.message(StateFilter(Adm.route_name))
async def on_route_name(msg: Message, state: FSMContext):
    pair = routes.parse_pair(msg.text or "")
    if not pair or not (known_city(pair[0]) and known_city(pair[1])):
        await msg.answer("❌ Shahar tanilmadi. Masalan: Toshkent - Samarqand. Bekor: /cancel")
        return
    a, b = canon_city(pair[0]), canon_city(pair[1])
    if a == b or any({r["city_a"], r["city_b"]} == {a, b} for r in crud.all_routes()):
        await msg.answer(f"ℹ️ {a} ↔ {b}: allaqachon bor yoki noto'g'ri. Boshqasini yuboring yoki /cancel")
        return
    await state.update_data(a=a, b=b)
    await state.set_state(Adm.route_chat)
    await msg.answer(f"🧭 {a} ↔ {b}\n\n" + CHAT_PROMPT, parse_mode="HTML")


async def _parse_chat(msg: Message, bot: Bot) -> tuple[int | None, str] | str:
    """(chat_id, title) yoki xato matni. chat_id=None — asosiy guruh."""
    origin = msg.forward_origin
    src = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None) if origin else None
    if src is not None:
        cid = src.id
    else:
        raw = (msg.text or "").strip()
        if raw == "0":
            return None, ""
        if not raw.lstrip("-").isdigit():
            return "❌ chat_id raqam bo'lishi kerak (yoki xabarni forward qiling)."
        cid = int(raw)
    try:
        chat = await bot.get_chat(cid)
        me = await bot.get_chat_member(cid, bot.id)
    except TelegramAPIError:
        return "❌ Bot bu guruhni ko'ra olmadi. Avval botni guruhga qo'shing, keyin qayta yuboring."
    if me.status in ("left", "kicked"):
        return "❌ Bot bu guruhga a'zo emas. Botni qo'shing va qayta yuboring."
    return chat.id, chat.title or str(chat.id)


@router.message(StateFilter(Adm.route_chat))
async def on_route_chat(msg: Message, state: FSMContext, bot: Bot):
    res = await _parse_chat(msg, bot)
    if isinstance(res, str):
        await msg.answer(res + "\nBekor: /cancel")
        return
    cid, title = res
    d = await state.get_data()
    crud.add_route(d["a"], d["b"], cid, title)
    await state.clear()
    text, kb = routes_view()
    await msg.answer(f"✅ Qo'shildi: {d['a']} ↔ {d['b']}\n\n" + text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("ap:rchat:"))
async def on_route_edit(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Adm.route_edit_chat)
    await state.update_data(rid=int(cb.data[9:]))
    await cb.message.answer(CHAT_PROMPT, parse_mode="HTML")
    await cb.answer()


@router.message(StateFilter(Adm.route_edit_chat))
async def on_route_edit_chat(msg: Message, state: FSMContext, bot: Bot):
    res = await _parse_chat(msg, bot)
    if isinstance(res, str):
        await msg.answer(res + "\nBekor: /cancel")
        return
    cid, title = res
    crud.set_route_chat((await state.get_data())["rid"], cid, title)
    await state.clear()
    text, kb = routes_view()
    await msg.answer("✅ Yangilandi\n\n" + text, parse_mode="HTML", reply_markup=kb)


# ================= 4. Sozlamalar =================
SETTINGS = {
    "max_groups": ("Bitta haydovchi tanlay oladigan maks. guruhlar", 1, 50),
    "min_gap_sec": ("Guruhlar orasidagi minimal pauza (soniya)", 2, 120),
    "min_interval_min": ("Eng qisqa rassilka intervali (daqiqa)", 5, 240),
}


def settings_view():
    stop = crud.get_setting("global_stop")
    lines = ["⚙️ <b>Tizim sozlamalari</b>", ""]
    for k, (title, _, _) in SETTINGS.items():
        lines.append(f"• {title}: <b>{crud.get_setting(k)}</b>")
    gap = crud.get_setting("min_gap_sec")
    lines.append(f"\nGuruhlar orasida tasodifiy pauza: {gap}–{gap + 7} s")
    lines.append(f"🚨 Global Stop: <b>{'YOQILGAN' if stop else 'o‘chiq'}</b>")
    kb = [[B(text=f"✏️ {t[:40]}", callback_data=f"ap:set:{k}")] for k, (t, _, _) in SETTINGS.items()]
    kb.append([B(text="✅ Global Stop'ni o'chirish" if stop else "🚨 Global Stop", callback_data="ap:gstop")])
    kb.append([BACK])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "ap:settings")
async def on_settings(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = settings_view()
    await _show(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ap:set:"))
async def on_setting_edit(cb: CallbackQuery, state: FSMContext):
    key = cb.data[7:]
    if key not in SETTINGS:
        await cb.answer()
        return
    title, lo, hi = SETTINGS[key]
    await state.set_state(Adm.setting)
    await state.update_data(key=key)
    await cb.message.answer(f"{title}\nHozir: {crud.get_setting(key)}\n\nYangi qiymat ({lo}–{hi}) yuboring. "
                            "Bekor: /cancel")
    await cb.answer()


@router.message(StateFilter(Adm.setting))
async def on_setting_value(msg: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    _, lo, hi = SETTINGS[key]
    raw = (msg.text or "").strip()
    if not raw.isdigit() or not lo <= int(raw) <= hi:
        await msg.answer(f"❌ {lo} dan {hi} gacha butun son yuboring. Bekor: /cancel")
        return
    crud.set_setting(key, int(raw))
    await state.clear()
    text, kb = settings_view()
    await msg.answer("✅ Saqlandi\n\n" + text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "ap:gstop")
async def on_gstop(cb: CallbackQuery):
    if crud.get_setting("global_stop"):
        crud.set_setting("global_stop", 0)
        text, kb = settings_view()
        await _show(cb, "✅ Global Stop o'chirildi. Haydovchilar rassilkani qayta yoqishlari mumkin.\n\n" + text, kb)
        await cb.answer()
        return
    await _show(cb, f"🚨 Hozir {manager.running_count()} ta rassilka ishlayapti.\n"
                    "Hammasi darhol to'xtatilsinmi? Global Stop o'chirilmaguncha yangisini ham yoqib bo'lmaydi.",
                _kb([B(text="🚨 Ha, hammasini to'xtatish", callback_data="ap:gstop_do")],
                    [B(text="Bekor", callback_data="ap:settings")]))
    await cb.answer()


@router.callback_query(F.data == "ap:gstop_do")
async def on_gstop_do(cb: CallbackQuery):
    n = manager.running_count()
    crud.set_setting("global_stop", 1)
    manager.stop_all()
    log.warning("GLOBAL STOP: admin=%s, %d rassilka to'xtatildi", cb.from_user.id, n)
    text, kb = settings_view()
    await _show(cb, f"🚨 {n} ta rassilka to'xtatildi.\n\n" + text, kb)
    await cb.answer()


# ================= 5. Umumiy xabarnoma =================
AUDIENCE = {"all": "Hammaga", "driver": "Haydovchilarga", "passenger": "Yo'lovchilarga"}


@router.callback_query(F.data == "ap:bcast")
async def on_bcast(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Adm.bcast)
    await cb.message.answer("📢 Xabarnomani yuboring: matn, rasm yoki video (izoh bilan bo'lishi mumkin).\n"
                            "Keyin kimga yuborishni tanlaysiz. Bekor: /cancel")
    await cb.answer()


@router.message(StateFilter(Adm.bcast))
async def on_bcast_msg(msg: Message, state: FSMContext):
    if not (msg.text or msg.photo or msg.video or msg.animation or msg.document):
        await msg.answer("Matn, rasm yoki video yuboring. Bekor: /cancel")
        return
    await state.update_data(src_chat=msg.chat.id, src_id=msg.message_id)
    counts = {k: len(crud.all_user_ids(None if k == "all" else k)) for k in AUDIENCE}
    await msg.answer("Kimga yuborilsin?", reply_markup=_kb(
        *[[B(text=f"{v} ({counts[k]})", callback_data=f"ap:bc:{k}")] for k, v in AUDIENCE.items()],
        [B(text="❌ Bekor", callback_data="ap:menu")]))


@router.callback_query(F.data.startswith("ap:bc:"), StateFilter(Adm.bcast))
async def on_bcast_send(cb: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    if "src_id" not in d:
        await cb.answer("Avval xabarni yuboring", show_alert=True)
        return
    who = cb.data[6:]
    ids = crud.all_user_ids(None if who == "all" else who)
    await _show(cb, f"📢 {AUDIENCE.get(who, '')}: {len(ids)} kishiga yuborilmoqda...", None)
    await cb.answer()
    asyncio.create_task(_bcast_run(bot, cb.from_user.id, d["src_chat"], d["src_id"], ids))


async def _bcast_run(bot: Bot, admin_id: int, src_chat: int, src_id: int, ids: list[int]):
    ok = fail = 0
    for uid in ids:
        for _ in range(2):
            try:
                await bot.copy_message(uid, src_chat, src_id)
                ok += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue
            except TelegramAPIError:            # botni bloklagan va h.k.
                fail += 1
            break
        await asyncio.sleep(BROADCAST_DELAY)
    log.info("Xabarnoma: %d yetdi, %d yetmadi", ok, fail)
    try:
        await bot.send_message(admin_id, f"📢 Xabarnoma tugadi: ✅ {ok} · ❌ {fail}")
    except TelegramAPIError:
        pass
