"""Yopiq haydovchilar guruhi a'zolarini nazorat qilish (to'lov / bepul sinov).

Ish tartibi (admin panel → ⚙️ → «Guruh nazorati» = 1 bo'lsa):
  • Haydovchi yopiq guruhga kirdi → obunasi bo'lsa: xush kelibsiz.
    Obunasi yo'q, sinovni hali ishlatmagan → `trial_days` (3) kun bepul obuna beriladi (rassilka ham ishlaydi).
    Sinov oldin ishlatilgan va to'lamagan → darhol chiqariladi.
  • Muddat tugashiga 3 kundan kam qolsa — har kuni 1 marta eslatma.
  • Muddat tugadi → guruhdan chiqariladi (ban + unban: keyin qayta kira oladi), sababi aytiladi.
  • Admin /admin da obuna qo'shsa → chiqarilgan guruhlar uchun bir martalik kirish havolasi yuboriladi.

Eslatma avval shaxsiy chatga yuboriladi. Haydovchi botga /start bosmagan bo'lsa — guruhning o'zida
ismi bilan yoziladi va 10 daqiqadan keyin o'chiriladi (guruh to'lib ketmasligi uchun).

Botga yopiq guruhda ADMIN huquqi kerak: «a'zolarni bloklash» va «havola orqali taklif qilish».
Nazorat yoqilishidan OLDIN guruhda bo'lgan a'zolarga tegilmaydi (Telegram bot a'zolar ro'yxatini bermaydi) —
faqat yangi kirganlar hisobga olinadi.
"""
import asyncio
import html
import logging
import math
import time

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup

import config
import routes
from database import crud

log = logging.getLogger(__name__)
router = Router(name="membership")

DAY = 86400
CHECK_EVERY_SEC = 1800          # har 30 daqiqada tekshiradi
REMIND_GAP_SEC = 20 * 3600      # eslatma kuniga ko'pi bilan 1 marta
REMIND_BEFORE_SEC = 3 * DAY     # tugashiga shuncha qolganda eslatma boshlanadi
GROUP_NOTE_TTL = 600            # guruhga yozilgan eslatma 10 daqiqadan keyin o'chadi

_bot_username = {"v": None}
_chat_admins: dict[int, set[int]] = {}      # chat -> guruh adminlari (ularga tegilmaydi), 1 soat kesh
_chat_admins_ts: dict[int, float] = {}
_rights_warned: set[int] = set()


def enabled() -> bool:
    return bool(crud.get_setting("member_control"))


def _date(ts: float) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))


def _kb(bot_username: str | None = None):
    from handlers.common import contact_button
    rows = []
    btn = contact_button()
    if btn:
        rows.append([InlineKeyboardButton(text="💳 To'lov qilish (admin)", url=btn.url)])
    if bot_username:
        rows.append([InlineKeyboardButton(text="🤖 Botni ochish", url=f"https://t.me/{bot_username}?start=driver")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _username(bot: Bot) -> str | None:
    if _bot_username["v"] is None:
        try:
            _bot_username["v"] = (await bot.get_me()).username
        except TelegramAPIError:
            return None
    return _bot_username["v"]


async def _is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if user_id in config.ADMIN_IDS:
        return True
    now = time.time()
    if now - _chat_admins_ts.get(chat_id, 0) > 3600:
        try:
            _chat_admins[chat_id] = {m.user.id for m in await bot.get_chat_administrators(chat_id)}
            _chat_admins_ts[chat_id] = now
        except TelegramAPIError:
            return False
    return user_id in _chat_admins.get(chat_id, set())


async def _tell(bot: Bot, chat_id: int, user_id: int, name: str, text: str):
    """Avval shaxsiy chatga. Bot bilan suhbat ochilmagan bo'lsa — guruhda ismi bilan (10 daqiqada o'chadi)."""
    uname = await _username(bot)
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=_kb())
        return
    except TelegramAPIError:
        pass
    mention = f'<a href="tg://user?id={user_id}">{html.escape(name or "Haydovchi")}</a>'
    try:
        m = await bot.send_message(chat_id, f"{mention}\n{text}", parse_mode="HTML", reply_markup=_kb(uname))
    except TelegramAPIError:
        try:        # ism havolasini Telegram rad etsa (maxfiylik) — oddiy ism bilan
            m = await bot.send_message(chat_id, f"👤 {html.escape(name or '')}\n{text}", parse_mode="HTML",
                                       reply_markup=_kb(uname))
        except TelegramAPIError as e:
            log.info("[member] eslatma yuborilmadi (user=%s chat=%s): %s", user_id, chat_id, e)
            return

    async def _drop():
        await asyncio.sleep(GROUP_NOTE_TTL)
        try:
            await bot.delete_message(chat_id, m.message_id)
        except TelegramAPIError:
            pass
    asyncio.create_task(_drop())


async def kick(bot: Bot, chat_id: int, user_id: int, name: str, reason: str) -> bool:
    crud.member_kicked(chat_id, user_id)        # avval belgilaymiz: chiqish hodisasi yozuvni o'chirmasin
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)   # qayta kira olishi uchun
    except TelegramAPIError as e:
        crud.member_join(chat_id, user_id, now=time.time())     # chiqarib bo'lmadi — guruhda deb qoldiramiz
        msg = str(e).lower()
        if "participant" in msg or "not found" in msg:
            crud.member_left(chat_id, user_id)
            return False
        if chat_id not in _rights_warned:
            _rights_warned.add(chat_id)
            log.warning("[member] guruhdan chiqarib bo'lmadi (chat=%s): %s — botga «a'zolarni bloklash» "
                        "huquqini bering", chat_id, e)
            from services import health
            health.to_bugs(f"⚠️ <b>Guruh nazorati</b>: <code>{chat_id}</code> guruhidan to'lovsiz haydovchini "
                           f"chiqarib bo'lmadi.\nSabab: {html.escape(str(e)[:150])}\n"
                           "Botni guruhda admin qiling: «a'zolarni bloklash» huquqi bilan.")
        return False
    log.info("[member] chiqarildi: user=%s chat=%s (%s)", user_id, chat_id, reason)
    await _tell(bot, chat_id, user_id, name, reason)
    return True


def _name(user_id: int) -> str:
    row = crud.get_user(user_id)
    return (row["full_name"] if row else None) or ""


# ---------- yangi a'zo ----------
@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_join(ev: ChatMemberUpdated, bot: Bot):
    chat_id = ev.chat.id
    if chat_id not in routes.closed_chat_ids():
        return
    u = ev.new_chat_member.user
    if u.is_bot:
        return
    crud.touch_user(u.id, u.username, u.full_name)
    crud.member_join(chat_id, u.id)
    if not enabled() or await _is_chat_admin(bot, chat_id, u.id):
        return
    await on_member(bot, chat_id, u.id, u.full_name)


async def on_member(bot: Bot, chat_id: int, user_id: int, name: str, now: float | None = None):
    now = time.time() if now is None else now
    left = crud.sub_left(user_id, now)
    if left is None or left > 0:
        row = crud.get_user(user_id)
        await _tell(bot, chat_id, user_id, name,
                    f"👋 Yopiq haydovchilar guruhiga xush kelibsiz!\nObunangiz: {crud.sub_text(row, now)}")
        return
    if not crud.trial_used(user_id):
        days = crud.get_setting("trial_days")
        crud.use_trial(user_id, now)
        crud.add_subscription(user_id, days, now)
        until = crud.get_user(user_id)["sub_until"]
        await _tell(bot, chat_id, user_id, name,
                    f"👋 Xush kelibsiz! Sizga <b>{days} kun bepul</b> sinov berildi "
                    f"(<b>{_date(until)}</b> gacha).\n\n"
                    "✅ Yopiq guruhdagi yo'lovchi buyurtmalari\n"
                    "🤖 E'loningizni avtomatik tarqatish (/driver)\n\n"
                    "Muddat tugagach to'lov qilmasangiz, guruhdan avtomatik chiqarilasiz.")
        return
    await kick(bot, chat_id, user_id, name,
               "🔒 Bepul sinov muddatingiz avval ishlatilgan. Guruhda qolish uchun obuna to'lovini qiling — "
               "to'lovdan keyin qayta kirish havolasi avtomatik yuboriladi.")


@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def on_leave(ev: ChatMemberUpdated):
    crud.member_left(ev.chat.id, ev.old_chat_member.user.id)


# ---------- davriy tekshiruv ----------
async def check(bot: Bot, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    res = {"reminded": 0, "kicked": 0}
    if not enabled():
        return res
    closed = routes.closed_chat_ids()
    for r in crud.members_in_groups():
        chat_id, uid = r["chat_id"], r["user_id"]
        if chat_id not in closed or uid in config.ADMIN_IDS:
            continue
        left = crud.sub_left(uid, now)
        if left is None or left >= REMIND_BEFORE_SEC:
            continue
        if await _is_chat_admin(bot, chat_id, uid):
            continue
        name = _name(uid)
        if left <= 0:
            if await kick(bot, chat_id, uid, name,
                          "🔒 Obuna muddatingiz tugadi va siz yopiq haydovchilar guruhidan chiqarildingiz.\n"
                          "To'lov qilsangiz, qayta kirish havolasi avtomatik yuboriladi."):
                res["kicked"] += 1
            continue
        if now - (r["notified_at"] or 0) < REMIND_GAP_SEC:
            continue
        until = now + left
        days = math.ceil(left / DAY)
        when = ("<b>bugun</b>" if left < DAY else "<b>ertaga</b>" if left < 2 * DAY
                else f"<b>{days} kundan keyin</b>")
        await _tell(bot, chat_id, uid, name,
                    f"⏳ Obuna muddatingiz {when} tugaydi ({_date(until)}).\n"
                    "To'lov qilmasangiz, yopiq haydovchilar guruhidan avtomatik chiqarilasiz "
                    "va e'lon rassilkasi to'xtaydi.")
        crud.member_notified(chat_id, uid, now)
        res["reminded"] += 1
    return res


async def loop(bot: Bot):
    await asyncio.sleep(120)
    while True:
        try:
            res = await check(bot)
            if res["reminded"] or res["kicked"]:
                log.info("[member] eslatma: %s, chiqarildi: %s", res["reminded"], res["kicked"])
        except Exception:
            log.exception("[member] tekshiruvda xato")
        await asyncio.sleep(CHECK_EVERY_SEC)


# ---------- to'lovdan keyin ----------
async def on_paid(bot: Bot, user_id: int) -> str:
    """Obuna qo'shilganda: chiqarilgan guruhlar uchun bir martalik havola. Foydalanuvchiga qo'shiladigan matn."""
    links = []
    for chat_id in crud.kicked_chats(user_id):
        try:
            inv = await bot.create_chat_invite_link(chat_id, member_limit=1, expire_date=int(time.time()) + DAY,
                                                    name=f"paid {user_id}")
            links.append(inv.invite_link)
        except TelegramAPIError as e:
            log.warning("[member] havola yaratilmadi (chat=%s): %s — botga «havola orqali taklif» huquqi kerak",
                        chat_id, e)
    if not links:
        return ""
    return ("\n\n🔗 Yopiq guruhga qaytish havolasi (24 soat, bir martalik):\n" + "\n".join(links))
