"""
Ishga tushirish:  python main.py
MODE=bot      — bot guruhlarga a'zo (guruh egalari bilan hamkorlik)
MODE=userbot  — oddiy akkaunt begona guruhlarni o'qiydi, bot faqat haydovchilar guruhiga yozadi
MODE=both     — ikkalasi birga
"""
import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import AiogramError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admin
import config
import moderation
import order
import panel
import relay
import routes
import store
from database import crud
from handlers import admin_panel, driver_cabinet
from handlers.middlewares import TrackUsers
from nlp import fmt_phone
from pipeline import Incoming, process, sender
from services import donor_parser, learn, order_contact, userbot_coverage
from services.broadcaster import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("main")
router = Router()

_taken: dict[tuple[int, int], str] = {}     # (chat, xabar) -> kim oldi
_TAKEN_LIMIT = 5000


# ---------- 1-rejim: bot guruhlarda a'zo ----------
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text | F.caption)
async def on_group_message(msg: Message, bot: Bot):
    if msg.from_user and msg.from_user.is_bot:
        return
    if msg.chat.id in routes.closed_chat_ids():
        if msg.reply_to_message is not None:    # haydovchi #Order e'loniga reply qildi (har qanday rejimda)
            await on_order_reply(msg, bot)
        return
    if config.MODE == "userbot":
        return
    if (msg.text or "").startswith("/"):
        return
    if not store.find(msg.chat.id, msg.chat.username, msg.chat.title):
        return
    age = (datetime.now(timezone.utc) - msg.date).total_seconds()
    if age > config.MAX_AGE_MINUTES * 60:   # bot o'chiq turganda to'plangan eski xabar
        return
    u = msg.from_user
    label = await process(Incoming(
        text=msg.text or msg.caption, chat_id=msg.chat.id, chat_title=msg.chat.title or "",
        chat_username=msg.chat.username, msg_id=msg.message_id,
        user_name=u.full_name if u else None, username=u.username if u else None,
        user_id=u.id if u else None,
    ))
    if config.OFFER_IN_GROUPS and label == "passenger" and u:
        await order.offer_in_group(msg, bot)


# ---------- Kanal postlari (bot kanalda admin bo'lsa) ----------
@router.channel_post(F.text | F.caption)
async def on_channel_post(msg: Message):
    if config.MODE == "userbot":        # userbot rejimida kanalni akkaunt o'qiydi, ikki marta bo'lmasin
        return
    if msg.chat.id in routes.closed_chat_ids() or (msg.text or "").startswith("/"):
        return
    if not store.find(msg.chat.id, msg.chat.username, msg.chat.title):
        return
    age = (datetime.now(timezone.utc) - msg.date).total_seconds()
    if age > config.MAX_AGE_MINUTES * 60:
        return
    await process(Incoming(
        text=msg.text or msg.caption, chat_id=msg.chat.id, chat_title=msg.chat.title or "",
        chat_username=msg.chat.username, msg_id=msg.message_id,
        user_name=None, username=None, user_id=None,     # kanalda shaxsiy muallif yo'q
    ))


# ---------- "Oldim" tugmasi ----------
def _after_take_kb(cb: CallbackQuery, chat_url: str | None):
    """"Oldim" yo'qoladi, bog'lanish tugmalari qoladi."""
    old = cb.message.reply_markup.inline_keyboard if cb.message.reply_markup else []
    rows = [[b for b in row if b.url or (b.callback_data or "").startswith("oc:")] for row in old]
    rows = [row for row in rows if row]
    if chat_url:
        rows.append([InlineKeyboardButton(text="💬 Bot orqali yozish", url=chat_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.callback_query(F.data.regexp(r"^take(:\d+)?$"))
async def on_take(cb: CallbackQuery, bot: Bot):
    if not isinstance(cb.message, Message):  # juda eski xabar
        await cb.answer("Bu e'lon eskirgan", show_alert=True)
        return
    who = cb.from_user
    name = f"@{who.username}" if who.username else html.escape(who.full_name)
    key = (cb.message.chat.id, cb.message.message_id)
    if key in _taken or "✅ Band:" in (cb.message.text or ""):
        await cb.answer(f"Allaqachon olingan: {_taken.get(key, '')}".rstrip(": "), show_alert=True)
        return
    _taken[key] = name                      # birinchi "await" dan oldin band qilinadi, poyga bo'lmaydi
    if len(_taken) > _TAKEN_LIMIT:
        del _taken[next(iter(_taken))]
    passenger = int(cb.data.split(":")[1]) if ":" in cb.data else None
    chat_url = f"https://t.me/{(await bot.me()).username}?start=chat" if passenger else None
    try:
        await cb.message.edit_text(
            cb.message.html_text + f"\n\n✅ <b>Band:</b> {name}",
            parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=_after_take_kb(cb, chat_url),
        )
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            del _taken[key]
            log.error("E'lonni yangilab bo'lmadi: %s", e)
            await cb.answer("Xatolik, qayta urinib ko'ring", show_alert=True)
            return
    if passenger is None:
        await cb.answer("Siz oldingiz!")
        return
    route = next((x[1:].strip() for x in (cb.message.text or "").splitlines() if x.startswith("📍")), "")
    if await relay.connect(bot, who.id, passenger, route, name):
        await cb.answer("Siz oldingiz! Yo'lovchiga botda yozishingiz mumkin.")
    else:                                   # haydovchi botni hali ochmagan: Telegram botni ochib beradi
        await cb.answer(url=chat_url)


# ---------- «💬 Yozish» / reply: username'siz mijozga yozish ----------
async def _tell_driver(bot: Bot, who, text: str, reply_to: Message | None):
    try:                                    # natija haydovchiga shaxsan (botni ochgan bo'lsa)
        await bot.send_message(who.id, text, parse_mode="HTML")
    except AiogramError:                    # bo'lmasa guruhda e'longa javob qilib
        if reply_to is not None:
            mention = f"@{who.username}" if who.username else html.escape(who.full_name)
            await reply_to.reply(f"{mention}: {text}", parse_mode="HTML")


async def _mark_ad(ad: Message | None, line: str | None = None, url: str | None = None, order_no: int | None = None):
    """E'lonni yangilaydi: holat qatori qo'shadi va/yoki «💬 Yozish» ni lichka havolasiga aylantiradi."""
    if ad is None:
        return
    kb = ad.reply_markup
    if url and kb:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Lichkaga yozish", url=url) if b.callback_data == f"oc:{order_no}" else b
             for b in row]
            for row in kb.inline_keyboard])
    try:
        if line:
            await ad.edit_text(ad.html_text + "\n" + line, parse_mode="HTML", reply_markup=kb,
                               disable_web_page_preview=True)
        elif url:
            await ad.edit_reply_markup(reply_markup=kb)
    except AiogramError:
        pass


async def _contact_flow(bot: Bot, who, order_no: int, reply_to: Message | None):
    """«💬 Yozish» (username'siz mijoz). Har bir akkaunt mijozni shu tartibda qidiradi (order_contact.resolve_for):
    matndagi raqam → Telegram (asl xabar) → profildagi raqam.
    1) Haydovchining O'Z akkaunti — topsa: username bo'lsa lichka havolasi, bo'lmasa o'z nomidan yozadi.
    2) Topolmasa — asosiy userbot «haydovchi bog'lanmoqchi» deb yozadi (e'londa 🤖 belgisi bilan)."""
    ad = reply_to.reply_to_message if (reply_to is not None and reply_to.reply_to_message) else reply_to
    name = " ".join(x for x in (who.first_name, who.last_name) if x) or None
    mention = f"@{who.username}" if who.username else html.escape(who.full_name)
    res, username, via = "no_userbot", None, None
    async with manager.session(who.id) as own:      # haydovchi akkaunti faqat shu ish uchun ulanadi
        if own is not None:
            res, username = await order_contact.reach(own, order_no, who.id, who.username, name, as_driver=True)
            via = "driver"
    if res in ("no_userbot", "not_found_driver") and admin.userbot is not None:
        r2, u2 = await order_contact.reach(admin.userbot, order_no, who.id, who.username, name)
        if r2 in ("ok", "username") or res == "no_userbot":
            res, username, via = r2, u2, "userbot"

    if res == "username":
        url = f"https://t.me/{username}"
        await _mark_ad(ad, "🟢 Lichka topildi: @" + html.escape(username), url=url, order_no=order_no)
        await _tell_driver(bot, who, f"👤 Mijoz lichkasi: @{html.escape(username)}\n"
                                     "E'londagi tugma endi «💬 Lichkaga yozish» — lichkani to'g'ridan-to'g'ri ochadi.", reply_to)
        return
    if res == "ok":
        if via == "driver":
            await _mark_ad(ad, f"✍️ {mention} mijozga o'z akkauntidan yozdi")
            text = order_contact._REPLY["ok_driver"]
        else:
            await _mark_ad(ad, f"🤖 {mention} uchun bot mijozga yozdi (mijoz sizga javob beradi)")
            text = order_contact._REPLY["ok"]
    else:
        text = order_contact._REPLY.get(res, order_contact._REPLY["error"])
    await _tell_driver(bot, who, html.escape(text), reply_to)


@router.callback_query(F.data.regexp(r"^oc:\d+$"))
async def on_order_contact(cb: CallbackQuery, bot: Bot):
    await cb.answer("⏳ Mijozga xabar yuborilmoqda...")
    await _contact_flow(bot, cb.from_user, int(cb.data[3:]),
                        cb.message if isinstance(cb.message, Message) else None)


async def on_order_reply(msg: Message, bot: Bot):
    """Haydovchi yopiq guruhda bot e'loniga (#Order_N) reply qildi. Bot o'z xabariga reply'larni har doim ko'radi."""
    r = msg.reply_to_message
    if msg.chat.id not in routes.closed_chat_ids() or not (r.from_user and r.from_user.id == bot.id):
        return
    m = order_contact.ORDER_RE.search(r.text or r.caption or "")
    if not m or not msg.from_user:
        return
    await _contact_flow(bot, msg.from_user, int(m.group(1)), msg)


# ---------- 2-rejim: userbot (Telethon) ----------
async def run_userbot():
    from telethon import TelegramClient, events

    client = TelegramClient(str(config.BASE_DIR / config.SESSION_NAME), config.API_ID, config.API_HASH)
    me_id = {"id": None}                # userbot akkaunti ID (#Order: access_hash shu akkauntga tegishli)

    # chats= filtri ishlatilmaydi: u faqat startda o'qiladi, ro'yxat esa ish davomida o'zgaradi
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        # Guruh ham, kanal (broadcast) ham o'qiladi: akkaunt obuna bo'lsa yetarli, bot ichida bo'lishi shart emas
        if not ((event.is_group or event.is_channel) and event.raw_text) or event.chat_id in routes.closed_chat_ids():
            return
        if donor_parser.is_donor(event.chat_id):        # donor guruh: yashirin havola/User ID bilan alohida oqim
            await donor_parser.handle(event, exclude_sender_ids=set(manager.tg_ids.values()))
            return
        chat = await event.get_chat()
        # Kuzatuv ro'yxatidagi guruh/kanal YOKI haydovchilar tanlagan guruh. Haydovchi akkauntlari endi doim
        # ulanib turmaydi — ularning guruhlarini userbot o'qiydi (userbot_coverage u guruhlarga qo'shiladi).
        watched = store.find(event.chat_id, getattr(chat, "username", None), getattr(chat, "title", None))
        if not watched:
            if not (event.is_group and manager.is_selected_any(event.chat_id)):
                return
            if event.sender_id in manager.tg_ids.values():      # ulangan haydovchining o'z rassilkasi
                return
        if not manager.first_seen(event.chat_id, event.id):     # kuzatuvchi akkaunt ham o'qigan bo'lsa
            return
        broadcast = event.is_channel and not event.is_group     # kanal postida shaxsiy muallif yo'q
        sender_ = None if broadcast else await event.get_sender()
        if getattr(sender_, "bot", False):
            return
        first = getattr(sender_, "first_name", "") or ""
        last = getattr(sender_, "last_name", "") or ""
        await process(Incoming(
            text=event.raw_text, chat_id=event.chat_id, chat_title=getattr(chat, "title", ""),
            chat_username=getattr(chat, "username", None), msg_id=event.id,
            user_name=f"{first} {last}".strip() or None,
            username=getattr(sender_, "username", None), user_id=None if broadcast else event.sender_id,
            phone=None if broadcast else fmt_phone(getattr(sender_, "phone", None)),   # profil raqami ochiq bo'lsa
            access_hash=getattr(sender_, "access_hash", None), owner_id=me_id["id"],
        ))

    try:
        await client.start()  # birinchi marta telefon va kod so'raydi, keyin .session faylda saqlanadi
    except Exception as e:
        # API_ID/API_HASH noto'g'ri yoki login bo'lmadi: butun botni o'ldirmaymiz, bot-qismi ishlayveradi
        log.error("Userbot ishga tushmadi (%s). Bot faqat o'zi a'zo guruh/kanallarda ishlaydi. "
                  "my.telegram.org dan API_ID/API_HASH ni tekshiring.", e)
        await asyncio.Event().wait()    # bu vazifa abadiy kutadi, shu bilan main() to'xtamaydi
        return
    admin.userbot = client
    me_id["id"] = (await client.get_me()).id
    order_contact.register(client, routes.closed_chat_ids)   # haydovchi #Order ga reply qilsa — mijozga yozadi
    asyncio.create_task(userbot_coverage.loop(client, manager))   # haydovchilar/donor guruhlariga avto-qo'shilish
    log.info("Userbot ishga tushdi")
    try:
        await client.run_until_disconnected()
    finally:
        admin.userbot = None
        await client.disconnect()
    raise RuntimeError("Userbot ulanishi uzildi")  # bot "tirikdek" turib, xabar o'qimasdan qolmasin


async def preflight(bot: Bot):
    """Ko'p uchraydigan sozlash xatolarini startda aniq ko'rsatadi."""
    me = await bot.get_me()
    log.info("Bot: @%s | Rejim: %s | Guruhlar: %d", me.username, config.MODE, len(store.all_groups()))
    backends = config.ai_backends()
    if backends:
        log.info("AI: yoqilgan (%d backend: %s)", len(backends), ", ".join(m for _, _, m in backends))
    else:
        log.warning("AI: o'chiq (AI_API_KEY bo'sh). Noaniq xabarlar tashlanadi, faqat kalit so'zli e'lonlar o'tadi.")
    if config.MODE in ("bot", "both") and not me.can_read_all_group_messages:
        log.warning("Bot guruh xabarlarini O'QIY OLMAYDI. BotFather -> /setprivacy -> Disable, "
                    "keyin botni guruhlardan chiqarib, qayta qo'shing.")
    try:
        chat = await bot.get_chat(config.DRIVERS_CHAT_ID)
        log.info("Haydovchilar guruhi: %s", chat.title)
    except AiogramError as e:
        log.error("Haydovchilar guruhiga kirib bo'lmadi (%s). Botni guruhga qo'shing va "
                  "DRIVERS_CHAT_ID ni tekshiring.", e)


async def main():
    config.validate()
    if config.USE_SYSTEM_CA:
        import truststore
        truststore.inject_into_ssl()

    crud.counts()                       # bazani ochadi, jadvallarni yaratadi, eski JSON'larni ko'chiradi
    from services import crypto, security
    security.harden()                   # maxfiy fayllar 600, kalitlar bo'yicha ogohlantirish
    if config.SESSION_SECRET and "," in config.SESSION_SECRET:     # kalit rotatsiyasi: yangi kalitga o'tkazish
        log.warning("[security] %s ta sessiya yangi kalit bilan qayta shifrlandi. Endi eski kalitni "
                    "SESSION_SECRET dan olib tashlang.", crypto.rotate_all())
    db_chat = crud.get_setting("drivers_chat_id")   # admin paneldan tanlangan asosiy guruh .env dan ustun
    if db_chat:
        config.DRIVERS_CHAT_ID = db_chat
    if not config.DRIVERS_CHAT_ID:
        raise SystemExit("Asosiy yopiq guruh yo'q: .env ga DRIVERS_CHAT_ID yozing "
                         "(keyin /admin -> ⚙️ Tizim sozlamalari dan almashtirish mumkin)")
    bot = Bot(config.BOT_TOKEN)
    await preflight(bot)
    dp = Dispatcher()
    dp.message.outer_middleware(TrackUsers())
    dp.callback_query.outer_middleware(TrackUsers())
    # buyruqlar umumiy handlerdan oldin; moderatsiya reklamani taksi tahliliga yetmasdan o'chiradi.
    # driver_cabinet reply-tugmalari order dagi "erkin matn" handleridan oldin turishi shart.
    dp.include_routers(admin.router, admin_panel.router, moderation.router, panel.router,
                       driver_cabinet.router, relay.router, order.router, router)

    await manager.start(bot)            # haydovchi akkauntlarini ulaydi, to'xtamagan rassilkalarni davom ettiradi
    polling = asyncio.create_task(dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()))
    tasks = [polling, asyncio.create_task(sender(bot))]
    asyncio.create_task(order_contact.purge_loop())     # #Order yozuvlari muddati o'tgach o'chiriladi (har rejimda)
    if config.MODE in ("userbot", "both"):
        tasks.append(asyncio.create_task(run_userbot()))

    # Bittasi tugasa (Ctrl+C, xato, userbot uzilishi) qolganlari ham to'xtaydi
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await manager.shutdown()
    learn.save()                        # o'rganilgan belgilarni diskka yozamiz
    await bot.session.close()
    for t in done:
        t.result()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
