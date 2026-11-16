"""Bot orqali boshqaruv: kuzatiladigan guruhlarni qo'shish/o'chirish, statistika, /id."""
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter, Command, CommandObject
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import moderation
import store
from pipeline import stats

log = logging.getLogger(__name__)
router = Router()
userbot = None      # MODE=userbot/both da main.py Telethon clientni shu yerga qo'yadi

HELP = (
    "<b>Guruhlarni boshqarish</b>\n"
    "/add — shu guruhni qo'shish (guruh ichida yoziladi)\n"
    "/addgroup @guruh — username, t.me havola yoki ID bilan qo'shish\n"
    "/delgroup @guruh — o'chirish\n"
    "/groups — ro'yxat va o'chirish tugmalari\n"
    "/stats — statistika\n\n"
    "Botni yangi guruhga qo'shsangiz, o'zi kuzatuvga olinadi."
)


async def is_admin(bot: Bot, user_id) -> bool:
    if user_id in config.ADMIN_IDS:
        return True
    try:
        member = await bot.get_chat_member(config.DRIVERS_CHAT_ID, user_id)
    except TelegramAPIError as e:
        log.warning("Admin holatini tekshirib bo'lmadi: user=%s: %s", user_id, e)
        return False
    allowed = member.status in ("creator", "administrator")
    if not allowed:
        log.info("Admin emas: user=%s status=%s", user_id, member.status)
    return allowed


def parse_ref(text: str):
    """@guruh, t.me/guruh, t.me/c/123/4 yoki -100123 -> @username yoki int. Tushunilmasa None."""
    s = text.strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    m = re.fullmatch(r"(?:https?://)?t\.me/c/(\d+)(?:/\d+)*/?", s)
    if m:
        return int(f"-100{m.group(1)}")
    m = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,})(?:/\d+)?/?", s)
    if m and m.group(1).lower() != "joinchat":
        return f"@{m.group(1)}"
    m = re.fullmatch(r"@?([A-Za-z][A-Za-z0-9_]{3,})", s)
    return f"@{m.group(1)}" if m else None


async def resolve(bot: Bot, ref) -> tuple[int, str | None, str, str]:
    """Guruh/kanalni topadi va o'qish mumkinligini tekshiradi. (id, username, title, kind). Bo'lmasa ValueError."""
    if userbot is not None:
        # Userbot rejimida akkaunt guruh/kanalga obuna bo'lib, bot ichida bo'lmasa ham o'qiydi
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.utils import get_peer_id

        entity = await userbot.get_entity(ref)
        await userbot(JoinChannelRequest(entity))   # allaqachon a'zo bo'lsa ham xato bermaydi
        kind = "channel" if getattr(entity, "broadcast", False) else "group"
        return get_peer_id(entity), getattr(entity, "username", None), getattr(entity, "title", ""), kind

    try:
        chat = await bot.get_chat(ref)
    except TelegramAPIError:
        raise ValueError("topilmadi. Avval botni shu guruh/kanalga qo'shing") from None
    if chat.type not in ("group", "supergroup", "channel"):
        raise ValueError("bu guruh yoki kanal emas")
    kind = "channel" if chat.type == "channel" else "group"
    me = await bot.get_chat_member(chat.id, bot.id)
    if kind == "channel" and me.status != "administrator":
        raise ValueError("botni kanalga ADMIN qiling (kanal postlarini faqat admin bot o'qiydi)")
    if me.status in ("left", "kicked"):
        raise ValueError("bot bu guruhga a'zo emas. Botni guruhga qo'shing, o'zi kuzatuvga olinadi")
    return chat.id, chat.username, chat.title or "", kind


async def add_watch(bot: Bot, raw: str) -> str:
    """Bitta guruh/kanalni qo'shadi, foydalanuvchiga ko'rsatiladigan natija satrini qaytaradi."""
    ref = parse_ref(raw)
    if ref is None:
        return f"❌ {raw}: tushunilmadi (yopiq havola qo'llab-quvvatlanmaydi)"
    try:
        chat_id, username, title, kind = await resolve(bot, ref)
    except ValueError as e:
        return f"❌ {raw}: {e}"
    except Exception as e:      # Telethon: topilmadi, limit va h.k.
        log.warning("Qo'shib bo'lmadi %s: %s", raw, e)
        return f"❌ {raw}: {e}"
    if chat_id == config.DRIVERS_CHAT_ID:
        return f"❌ {raw}: bu haydovchilar guruhi"
    tag = "Kanal" if kind == "channel" else "Guruh"
    if store.add(chat_id, username, title, kind):
        return f"✅ {tag}: {title or raw} qo'shildi"
    return f"ℹ️ {title or raw}: allaqachon bor"


def _ref_of(g: dict) -> str:
    return str(g["id"]) if g["id"] is not None else f"@{g['username']}"


def _label(g: dict) -> str:
    return g["title"] or (f"@{g['username']}" if g["username"] else str(g["id"]))


def _icon(g: dict) -> str:
    return "📢" if store.kind_of(g) == "channel" else "👥"


def _groups_view():
    groups = store.all_groups()
    if not groups:
        return "Hozircha manba yo'q. Tugma orqali yoki /addgroup bilan guruh/kanal qo'shing.", None
    n_ch = sum(1 for g in groups if store.kind_of(g) == "channel")
    lines = [f"<b>Kuzatilayotgan manbalar: {len(groups)}</b> ({len(groups) - n_ch} guruh, {n_ch} kanal)"]
    lines += [f"{i}. {_icon(g)} {html.escape(_label(g))}" for i, g in enumerate(groups, 1)]
    kb = [[InlineKeyboardButton(text=f"❌ {i}. {_icon(g)} {_label(g)[:36]}", callback_data=f"gdel:{_ref_of(g)}")]
          for i, g in enumerate(groups, 1)]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


# ---------- Hamma uchun ----------
@router.message(Command("id"))
async def on_id(msg: Message):
    await msg.answer(f"Chat ID: <code>{msg.chat.id}</code>", parse_mode="HTML")


# ---------- Faqat admin ----------
@router.message(Command("help"), F.chat.type == "private")
async def on_help(msg: Message, bot: Bot):
    if await is_admin(bot, msg.from_user.id):
        await msg.answer(HELP, parse_mode="HTML")
    else:
        await msg.answer("Taksi buyurtma qilish: /order\nBekor qilish: /cancel")


@router.message(Command("stats"))
async def on_stats(msg: Message, bot: Bot):
    if msg.from_user and await is_admin(bot, msg.from_user.id):
        await msg.answer("\n".join(f"{k}: {v}" for k, v in stats.items()))


@router.message(Command("add"), F.chat.type.in_({"group", "supergroup"}))
async def on_add_here(msg: Message, bot: Bot):
    if not (msg.from_user and await is_admin(bot, msg.from_user.id)):
        return
    if msg.chat.id == config.DRIVERS_CHAT_ID:
        await msg.answer("Bu haydovchilar guruhi, uni kuzatib bo'lmaydi.")
        return
    new = store.add(msg.chat.id, msg.chat.username, msg.chat.title or "")
    await msg.answer("✅ Guruh qo'shildi." if new else "Bu guruh allaqachon ro'yxatda.")


@router.message(Command("addgroup"))
async def on_add_group(msg: Message, command: CommandObject, bot: Bot):
    if not (msg.from_user and await is_admin(bot, msg.from_user.id)):
        return
    if not command.args:
        await msg.answer("Misol: /addgroup @toshkent_taksi")
        return
    out = [await add_watch(bot, raw) for raw in command.args.split()]
    await msg.answer("\n".join(out))


@router.message(Command("delgroup"))
async def on_del_group(msg: Message, command: CommandObject, bot: Bot):
    if not (msg.from_user and await is_admin(bot, msg.from_user.id)):
        return
    if not command.args:
        await msg.answer("Misol: /delgroup @toshkent_taksi yoki ro'yxatdan: /groups")
        return
    out = []
    for raw in command.args.split():
        ref = parse_ref(raw)
        gone = ref is not None and (store.remove(chat_id=ref) if isinstance(ref, int) else store.remove(username=ref))
        out.append(f"🗑 {raw}: o'chirildi" if gone else f"❌ {raw}: ro'yxatda yo'q")
    await msg.answer("\n".join(out))


@router.message(Command("groups"))
async def on_groups(msg: Message, bot: Bot):
    if not (msg.from_user and await is_admin(bot, msg.from_user.id)):
        return
    text, kb = _groups_view()
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("gdel:"))
async def on_group_delete(cb: CallbackQuery, bot: Bot):
    if not await is_admin(bot, cb.from_user.id):
        await cb.answer(f"Faqat adminlar uchun. Sizning ID: {cb.from_user.id}", show_alert=True)
        return
    ref = parse_ref(cb.data[5:])
    if isinstance(ref, int):
        store.remove(chat_id=ref)
    else:
        store.remove(username=ref)
    text, kb = _groups_view()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("O'chirildi")


@router.callback_query(F.data.startswith("gadd:"))
async def on_group_approve(cb: CallbackQuery, bot: Bot):
    if not await is_admin(bot, cb.from_user.id):
        await cb.answer(f"Faqat adminlar uchun. Sizning ID: {cb.from_user.id}", show_alert=True)
        return
    chat_id = int(cb.data[5:])
    chat = await bot.get_chat(chat_id)
    kind = "channel" if chat.type == "channel" else "group"
    store.add(chat_id, chat.username, chat.title or "", kind)
    await cb.message.edit_text(f"✅ Kuzatuvga olindi: {html.escape(chat.title or str(chat_id))}", parse_mode="HTML")
    await cb.answer()


# ---------- Bot guruh yoki kanalga qo'shilganda ----------
@router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION), F.chat.type.in_({"group", "supergroup", "channel"}))
async def on_bot_added(event: ChatMemberUpdated, bot: Bot):
    chat = event.chat
    if chat.id == config.DRIVERS_CHAT_ID:
        return
    kind = "channel" if chat.type == "channel" else "group"
    title = html.escape(chat.title or str(chat.id))
    if kind == "group":
        await moderation.welcome(bot, chat.id)
    adder = event.from_user.id if event.from_user else None
    if adder is not None and await is_admin(bot, adder):
        store.add(chat.id, chat.username, chat.title or "", kind)
        log.info("Yangi %s avtomatik qo'shildi: %s", kind, chat.title)
        return
    # Begona odam botni o'z guruhi/kanaliga qo'shib, haydovchilarga spam yubora olmasin
    what = "kanalga" if kind == "channel" else "guruhga"
    await bot.send_message(
        config.DRIVERS_CHAT_ID,
        f"🆕 Bot yangi {what} qo'shildi: <b>{title}</b>\nKuzatuvga olinsinmi? (faqat adminlar bosa oladi)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Kuzatish", callback_data=f"gadd:{chat.id}")
        ]]),
    )


@router.my_chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION), F.chat.type.in_({"group", "supergroup", "channel"}))
async def on_bot_removed(event: ChatMemberUpdated):
    if store.find(event.chat.id):
        log.warning("Bot %s dan chiqarildi: %s. Qayta qo'shmaguncha xabar kelmaydi.", event.chat.type, event.chat.title)


@router.message(F.migrate_to_chat_id)
async def on_migrate(msg: Message):
    store.migrate(msg.chat.id, msg.migrate_to_chat_id)
    moderation.migrate(msg.chat.id, msg.migrate_to_chat_id)
