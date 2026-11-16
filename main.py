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
from pipeline import Incoming, process, sender
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
    if config.MODE == "userbot" or (msg.from_user and msg.from_user.is_bot):
        return
    if msg.chat.id in routes.closed_chat_ids() or (msg.text or "").startswith("/"):
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
    rows = [[b for b in row if b.url] for row in old]
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


# ---------- 2-rejim: userbot (Telethon) ----------
async def run_userbot():
    from telethon import TelegramClient, events

    client = TelegramClient(str(config.BASE_DIR / config.SESSION_NAME), config.API_ID, config.API_HASH)

    # chats= filtri ishlatilmaydi: u faqat startda o'qiladi, ro'yxat esa ish davomida o'zgaradi
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        # Guruh ham, kanal (broadcast) ham o'qiladi: akkaunt obuna bo'lsa yetarli, bot ichida bo'lishi shart emas
        if not ((event.is_group or event.is_channel) and event.raw_text) or event.chat_id in routes.closed_chat_ids():
            return
        chat = await event.get_chat()
        # Faqat kuzatuv ro'yxatidagi guruh/kanal (haydovchilar tanlagan guruhlarni services/broadcaster o'qiydi)
        if not store.find(event.chat_id, getattr(chat, "username", None), getattr(chat, "title", None)):
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
    if config.AI_API_KEY:
        log.info("AI: yoqilgan (model=%s)", config.AI_MODEL)
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
    if config.MODE in ("userbot", "both"):
        tasks.append(asyncio.create_task(run_userbot()))

    # Bittasi tugasa (Ctrl+C, xato, userbot uzilishi) qolganlari ham to'xtaydi
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await manager.shutdown()
    await bot.session.close()
    for t in done:
        t.result()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
