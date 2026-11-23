"""Ko'p sessiyali userbot menejeri.

XOTIRA TEJASH (2026-11-23): oddiy haydovchi akkaunti DOIM ulanib turmaydi — faqat rassilka sikli, guruh
ro'yxati yoki «Bot orqali yozish» paytida ulanadi (session() kontekst menejeri) va ishi tugagach uziladi.
Qayta login yo'q: bazadagi shifrlangan sessiya kaliti bilan ulanadi. Yo'lovchilarni o'qishni asosiy userbot
qiladi (userbot_coverage barcha guruhlarga qo'shiladi). Admin belgilagan «kuzatuvchi» akkauntlar (watchers)
doim ulangan va o'z guruhlarini o'qiydi — userbot kira olmagan yopiq guruhlar uchun.

Har bir haydovchi o'z Telegram akkauntini bot ichida ulaydi (services/userbot_auth.py). Ulangan har akkaunt:
  1. O'QIYDI: haydovchi tanlagan guruhlardagi yangi xabarlar pipeline.process ga beriladi — yo'lovchi
     e'lonlari yo'nalishga qarab yopiq guruhga tushadi. Bir xabarni bir nechta akkaunt ko'rsa, bir marta
     ishlanadi; ulangan haydovchilarning o'z e'lonlari o'qilmaydi.
  2. TARQATADI: «🚀 Tarqatishni boshlash» bosilsa, fon vazifasi (asyncio.create_task) e'lon matnini
     tanlangan guruhlarga navbat bilan yuboradi va intervaldan keyin takrorlaydi.

Anti-spam: guruhlar orasida random.uniform(min_gap, min_gap + 7) soniya; kunlik sikl chegarasi.
Xatolar: FloodWait — kutish; yozish taqiqlangan guruh — o'tkazib yuborish va tanlovdan chiqarish;
sessiya bekor qilingan — bazadan o'chirish va haydovchini ogohlantirish.
"""
import asyncio
import contextlib
import logging
import random
import time
from collections import OrderedDict

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
import routes
from database import crud
from services import crypto

log = logging.getLogger(__name__)

# Bu xatolar bitta guruhga tegishli: o'tkazib yuboriladi
SKIP_ERRORS = ("ChatWriteForbiddenError", "ChannelPrivateError", "UserBannedInChannelError",
               "ChatAdminRequiredError", "ChatRestrictedError", "ChatSendPlainForbiddenError",
               "ChatGuestSendForbiddenError", "ChannelInvalidError", "PeerIdInvalidError")
# Bu xatolar akkaunt sessiyasi o'lganini bildiradi
REVOKED_ERRORS = ("AuthKeyUnregisteredError", "SessionRevokedError", "UserDeactivatedError",
                  "UserDeactivatedBanError", "AuthKeyDuplicatedError", "SessionExpiredError")
MAX_FLOOD_WAIT = 3600       # bundan uzoq FloodWait bo'lsa rassilka to'xtatiladi (akkauntni asrash uchun)


class Halt(Exception):
    """Rassilka sikli to'xtatilsin (sessiya saqlanadi)."""


class Revoked(Halt):
    """Sessiya o'lgan va bazadan o'chirilgan."""


def _name(e: Exception) -> str:
    return type(e).__name__


def default_factory(session_str: str, receive_updates: bool = True):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    # receive_updates=False: vaqtinchalik ulanishda yangiliklar oqimi olinmaydi — tez va xotira tejaladi
    return TelegramClient(StringSession(session_str), config.API_ID, config.API_HASH,
                          receive_updates=receive_updates)


class Manager:
    def __init__(self):
        self.bot: Bot | None = None
        self.clients: dict[int, object] = {}        # HOZIR ulangan clientlar (kuzatuvchilar + vaqtinchalik)
        self.linked: set[int] = set()               # akkaunt ulangan (sessiya bazada) haydovchilar
        self.tg_ids: dict[int, int] = {}            # bot user_id -> Telegram akkaunt id
        self._users: dict[int, int] = {}            # vaqtinchalik ulanishdan nechta ish foydalanyapti
        self._locks: dict[int, asyncio.Lock] = {}
        self._temp: set[int] = set()                # session() o'zi ulagan (ish tugagach uziladigan) clientlar
        self.tasks: dict[int, asyncio.Task] = {}    # faol rassilkalar
        self.selected: dict[int, set[int]] = {}     # o'qiladigan guruhlar keshi
        self._seen: OrderedDict = OrderedDict()     # (chat_id, msg_id) — bir xabar bir marta
        self.factory = default_factory
        self.sleep = asyncio.sleep                  # testlarda tezlashtiriladi

    # ---------- holat ----------
    def is_connected(self, uid: int) -> bool:
        """Akkaunt ulanganmi (sessiya bor). Telegram'ga hozir ulanib turishi shart emas."""
        return uid in self.linked or uid in self.clients

    def is_live(self, uid: int) -> bool:
        return uid in self.clients

    def is_running(self, uid: int) -> bool:
        t = self.tasks.get(uid)
        return t is not None and not t.done()

    def connected_count(self) -> int:
        return len(self.linked | set(self.clients))

    def live_count(self) -> int:
        return len(self.clients)

    def running_count(self) -> int:
        return sum(1 for t in self.tasks.values() if not t.done())

    def is_selected_any(self, chat_id: int) -> bool:
        """Biror haydovchi shu guruhni tanlaganmi (userbot bu guruhlarni ham o'qiydi)."""
        return any(chat_id in s for s in self.selected.values())

    def first_seen(self, chat_id: int, msg_id: int) -> bool:
        """Xabar birinchi marta ko'rildimi (userbot va kuzatuvchi akkauntlar bir xabarni ikki marta bermasin)."""
        key = (chat_id, msg_id)
        if key in self._seen:
            return False
        self._seen[key] = True
        while len(self._seen) > 5000:
            self._seen.popitem(last=False)
        return True

    def refresh_selected(self, uid: int | None = None):
        sel = crud.all_selected_chat_ids()
        if uid is None:
            self.selected = sel
        else:
            self.selected[uid] = sel.get(uid, set())

    # ---------- ishga tushirish ----------
    async def start(self, bot: Bot):
        """Bot ishga tushganda bazadagi barcha sessiyalarni ulaydi va to'xtamagan rassilkalarni davom ettiradi."""
        self.bot = bot
        self.refresh_selected()
        if not (config.API_ID and config.API_HASH):
            if crud.all_sessions():
                log.error("API_ID/API_HASH yo'q: haydovchi sessiyalari ulanmadi")
            return
        for row in crud.all_sessions():
            uid = row["user_id"]
            s = crypto.decrypt(row["session_enc"])
            if s is None:
                log.error("Sessiya ochilmadi (kalit almashganmi?) user=%s", uid)
                await self.revoke(uid, "Sessiyani ochib bo'lmadi. Akkauntni qayta ulang.")
                continue
            self.linked.add(uid)
            if row["tg_user_id"]:
                self.tg_ids[uid] = row["tg_user_id"]
            if crud.is_watcher(uid):            # kuzatuvchi: doim ulangan, o'qiydi
                try:
                    await self.connect(uid, self.factory(s))
                except Revoked:
                    continue
                except Exception as e:          # tarmoq: keyingi restartda qayta uriniladi
                    log.error("Kuzatuvchi akkaunt ulanmadi user=%s: %s", uid, e)
            if row["is_running"] and not crud.get_setting("global_stop") and crud.has_access(uid):
                self._spawn(uid)
        log.info("Haydovchi akkauntlari: %d ta (doim onlayn kuzatuvchi: %d), %d rassilka davom etmoqda",
                 self.connected_count(), self.live_count(), self.running_count())

    # ---------- talab bo'yicha ulanish ----------
    @contextlib.asynccontextmanager
    async def session(self, uid: int):
        """Haydovchi akkauntini ish vaqtiga ulaydi: `async with manager.session(uid) as client:`.
        Allaqachon ulangan bo'lsa (kuzatuvchi yoki boshqa ish) — o'shani beradi. Oxirgi ish tugagach uzadi
        (kuzatuvchi bundan mustasno). Akkaunt yo'q/sessiya o'lgan bo'lsa client = None."""
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            client = self.clients.get(uid)
            if client is None and uid in self.linked:
                row = crud.get_session(uid)
                s = crypto.decrypt(row["session_enc"]) if row else None
                if s is None:
                    await self.revoke(uid, "Sessiyani ochib bo'lmadi. Akkauntni qayta ulang.")
                else:
                    try:
                        await self.connect(uid, self.factory(s, receive_updates=False), reader=False)
                        client = self.clients.get(uid)
                        if client is not None:
                            self._temp.add(uid)
                    except Revoked:
                        client = None
                    except Exception as e:
                        log.warning("Akkaunt ulanmadi user=%s: %s", uid, e)
                        client = None
            if client is not None:
                self._users[uid] = self._users.get(uid, 0) + 1
        try:
            yield client
        finally:
            if client is not None:
                self._users[uid] -= 1
                if self._users[uid] <= 0:
                    self._users.pop(uid, None)
                    if uid in self._temp and not crud.is_watcher(uid) and self.clients.get(uid) is client:
                        self._temp.discard(uid)
                        self.clients.pop(uid, None)
                        await self._drop_client(client)

    async def set_watcher(self, uid: int, on: bool):
        """Admin: akkauntni doimiy «kuzatuvchi» qiladi yoki oddiy (talab bo'yicha) holatga qaytaradi."""
        crud.set_watcher(uid, on)
        if on and uid in self.linked and uid not in self.clients:
            row = crud.get_session(uid)
            s = crypto.decrypt(row["session_enc"]) if row else None
            if s:
                await self.connect(uid, self.factory(s))
        elif not on and uid in self.clients and not self._users.get(uid):
            self._temp.discard(uid)
            await self._drop_client(self.clients.pop(uid))

    async def connect(self, uid: int, client, authorized: bool = False, reader: bool = True):
        """Clientni ro'yxatga oladi (reader=True bo'lsa o'qish handlerini ham ulaydi). Avtorizatsiya yo'q bo'lsa
        Revoked. Yangi ulangan (login) akkaunt kuzatuvchi bo'lmasa — ro'yxatga olinib, darhol uziladi."""
        if not authorized:
            if not client.is_connected():
                await client.connect()
            if not await client.is_user_authorized():
                await self.revoke(uid, "Telegram sessiyani bekor qildi.", client=client)
                raise Revoked()
        me = await client.get_me()
        old = self.clients.get(uid)
        if old is not None and old is not client:
            await self._drop_client(old)
        self.clients[uid] = client
        self.linked.add(uid)
        self.tg_ids[uid] = me.id
        self.refresh_selected(uid)
        if reader and crud.is_watcher(uid):
            self._attach_reader(uid, client)
        elif authorized and not self._users.get(uid):    # login tugadi, oddiy akkaunt: hozircha uzamiz
            self.clients.pop(uid, None)
            await self._drop_client(client)

    def _attach_reader(self, uid: int, client):
        try:
            from telethon import events
        except ImportError:         # testlarda telethon bo'lmasligi mumkin
            return

        async def handler(event):
            await self.on_message(uid, event)

        client.add_event_handler(handler, events.NewMessage(incoming=True))

    # ---------- o'qish ----------
    async def on_message(self, uid: int, event):
        """Haydovchi tanlagan guruhdagi xabar -> pipeline. Boshqa akkaunt allaqachon ko'rgan bo'lsa o'tkaziladi."""
        chat_id = event.chat_id
        from services import donor_parser
        if donor_parser.is_donor(chat_id):              # haydovchi akkaunti donor guruhga a'zo bo'lsa ham o'qiladi
            await donor_parser.handle(event, exclude_sender_ids=set(self.tg_ids.values()))
            return
        if chat_id not in self.selected.get(uid, ()) or not getattr(event, "is_group", False):
            return
        text = event.raw_text
        if not text or chat_id in routes.closed_chat_ids():
            return
        if not self.first_seen(chat_id, event.id):
            return
        if event.sender_id in self.tg_ids.values():     # ulangan haydovchining o'z e'loni
            return
        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return
        chat = await event.get_chat()
        from nlp import fmt_phone
        from pipeline import Incoming, process
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        await process(Incoming(
            text=text, chat_id=chat_id, chat_title=getattr(chat, "title", "") or "",
            chat_username=getattr(chat, "username", None), msg_id=event.id,
            user_name=f"{first} {last}".strip() or None,
            username=getattr(sender, "username", None), user_id=event.sender_id,
            phone=fmt_phone(getattr(sender, "phone", None)),        # profil raqami ochiq bo'lsa qo'shiladi
            access_hash=getattr(sender, "access_hash", None), owner_id=self.tg_ids.get(uid),   # #Order uchun
        ))

    # ---------- guruhlar ----------
    async def list_groups(self, uid: int) -> list[tuple[int, str]]:
        """Akkaunt a'zo bo'lgan guruh/superguruhlar (yopiq e'lon guruhlari chiqarib tashlanadi)."""
        closed = routes.closed_chat_ids()
        out = []
        async with self.session(uid) as client:
            if client is None:
                return []
            async for d in client.iter_dialogs():
                if getattr(d, "is_group", False) and d.id not in closed:
                    out.append((d.id, getattr(d, "title", "") or str(d.id)))
        return out

    # ---------- tarqatish ----------
    def can_start(self, uid: int) -> str | None:
        """Rassilkani yoqib bo'lmasa sababini qaytaradi."""
        if crud.get_setting("global_stop"):
            return "🚨 Admin barcha rassilkalarni vaqtincha to'xtatgan."
        if crud.is_blocked(uid):
            return "🚫 Siz bloklangansiz."
        if not crud.has_access(uid):
            return "🔒 Rassilka uchun ruxsat (obuna) yo'q. Admin bilan bog'laning."
        if not self.is_connected(uid):
            return "🔐 Avval akkauntni ulang."
        row = crud.get_session(uid)
        if not (row and row["ad_text"]):
            return "✍️ Avval e'lon matnini kiriting."
        if not crud.selected_groups(uid):
            return "📋 Avval guruhlarni tanlang."
        return None

    def start_broadcast(self, uid: int) -> str | None:
        reason = self.can_start(uid)
        if reason:
            return reason
        crud.set_running(uid, True)
        self._spawn(uid)
        return None

    def _spawn(self, uid: int):
        if not self.is_running(uid):
            self.tasks[uid] = asyncio.create_task(self._loop(uid), name=f"broadcast:{uid}")

    def stop_broadcast(self, uid: int, persist: bool = True):
        t = self.tasks.pop(uid, None)
        if t is not None and not t.done() and t is not asyncio.current_task():
            t.cancel()          # o'z ichidan chaqirilsa (revoke) bekor qilinmaydi — sikl o'zi chiqadi
        if persist:
            crud.set_running(uid, False)

    def stop_all(self):
        for uid in list(self.tasks):
            self.stop_broadcast(uid)
        crud.stop_all_running()

    async def _loop(self, uid: int):
        first = True
        if crud.broadcast_started_at(uid) is None:     # eski (yangilanishdan oldin yoqilgan) rassilka: hozirdan sanaymiz
            crud.set_running(uid, True)
        try:
            while True:
                reason = None if self.is_connected(uid) else "akkaunt ulanmagan"
                if crud.get_setting("global_stop"):
                    reason = "admin barcha rassilkalarni to'xtatdi"
                elif not crud.has_access(uid):
                    reason = "obuna muddati tugadi yoki ruxsat olib qo'yildi"
                row = crud.get_session(uid)
                targets = crud.selected_groups(uid)
                if reason is None and not (row and row["ad_text"] and targets):
                    reason = "e'lon matni yoki guruhlar yo'q"
                max_h = crud.get_setting("broadcast_max_hours")
                started = crud.broadcast_started_at(uid)
                if reason is None and max_h and started and time.time() - started >= max_h * 3600:
                    crud.set_running(uid, False)
                    await self.notify(uid, f"⏰ Rassilka {max_h} soat ishladi va avtomatik o'chirildi.\n"
                                           "Davom ettirish uchun kabinetda «🚀 Tarqatishni boshlash» ni qayta bosing.")
                    log.info("Rassilka avto-o'chdi user=%s (%s soat)", uid, max_h)
                    return
                if reason:
                    crud.set_running(uid, False)
                    await self.notify(uid, f"🛑 Rassilka to'xtadi: {reason}.")
                    return
                if crud.rounds_today(uid) >= config.BROADCAST_MAX_PER_DAY:
                    await self.sleep(600)       # kunlik limit: ertangi kunni kutamiz
                    continue
                crud.start_round(uid)
                async with self.session(uid) as client:       # faqat sikl davomida ulanadi
                    if client is None:
                        if not self.is_connected(uid):        # sessiya o'lgan (revoke xabar bergan)
                            return
                        log.warning("Rassilka: akkaunt ulanmadi user=%s, keyingi siklda qayta uriniladi", uid)
                        ok, skipped = 0, []
                    else:
                        ok, skipped = await self._round(uid, row["ad_text"], targets)
                log.info("Rassilka user=%s: %d/%d guruh", uid, ok, len(targets))
                if first or skipped:
                    msg = f"📤 Sikl tugadi: {ok}/{len(targets)} guruhga yuborildi."
                    if skipped:
                        msg += ("\n\n⚠️ Yozib bo'lmadi, tanlovdan chiqarildi:\n"
                                + "\n".join(f"• {t}" for t in skipped))
                    if first:
                        msg += f"\n\nKeyingi sikl {row['interval_min']} daqiqadan keyin."
                        if max_h:
                            msg += f"\n⏰ Rassilka {max_h} soatdan keyin avtomatik o'chadi."
                    await self.notify(uid, msg)
                first = False
                await self.sleep(row["interval_min"] * 60)
        except Halt:
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Rassilka xatosi user=%s: %s", uid, e)
            crud.set_running(uid, False)
            await self.notify(uid, "❌ Rassilkada kutilmagan xato, to'xtatildi. Qayta yoqib ko'ring.")
        finally:
            if self.tasks.get(uid) is asyncio.current_task():
                self.tasks.pop(uid, None)

    async def _round(self, uid: int, text: str, targets: list[tuple[int, str]]) -> tuple[int, list[str]]:
        ok, skipped = 0, []
        gap = crud.get_setting("min_gap_sec")
        for i, (cid, title) in enumerate(targets):
            client = self.clients.get(uid)
            if client is None:
                break
            if i:
                await self.sleep(random.uniform(gap, gap + 7))
            for attempt in (1, 2):
                try:
                    if attempt == 1:
                        await self._delete_previous(uid, client, cid)
                    # parse_mode=None: haydovchi matnidagi * _ ` markdown deb buzilmasin
                    sent = await client.send_message(cid, text, parse_mode=None, link_preview=False)
                    crud.set_last_post(uid, cid, getattr(sent, "id", None))
                    crud.record_post(uid, cid)
                    ok += 1
                except Exception as e:
                    n = _name(e)
                    if n == "FloodWaitError" and attempt == 1:
                        wait = int(getattr(e, "seconds", 60))
                        if wait > MAX_FLOOD_WAIT:
                            crud.set_running(uid, False)
                            await self.notify(uid, f"⏳ Telegram {wait // 60} daqiqa kutishni talab qildi. "
                                                   "Akkauntni asrash uchun rassilka to'xtatildi.")
                            raise Halt() from e
                        log.warning("FloodWait user=%s: %s s", uid, wait)
                        await self.sleep(wait + 1)
                        continue
                    if n in REVOKED_ERRORS:
                        await self.revoke(uid, "Telegram akkauntingiz sessiyasi bekor qilingan.")
                        raise Revoked() from e
                    if n in SKIP_ERRORS:
                        crud.unselect_group(uid, cid)
                        self.refresh_selected(uid)
                        skipped.append(title or str(cid))
                    else:
                        log.warning("Yuborilmadi user=%s guruh=%s: %s", uid, cid, e)
                break
        return ok, skipped

    # ---------- uzish ----------
    async def _delete_previous(self, uid: int, client, cid: int):
        """Shu guruhga oldingi siklda yuborilgan e'lonni o'chiradi — guruhda har doim bitta, eng yangi e'lon.
        O'chirib bo'lmasa (allaqachon o'chirilgan, huquq yo'q) — jim davom etadi, yangisi baribir yuboriladi."""
        old = crud.last_post(uid, cid)
        if not old:
            return
        try:
            await client.delete_messages(cid, [old])
        except Exception as e:
            log.info("Eski e'lon o'chirilmadi user=%s guruh=%s: %s", uid, cid, _name(e))
        crud.set_last_post(uid, cid, None)

    async def disconnect(self, uid: int, logout: bool = True):
        """Haydovchi o'zi uzganda yoki admin sessiyani uzganda: rassilka to'xtaydi, sessiya o'chadi."""
        self.stop_broadcast(uid)
        client = self.clients.pop(uid, None)
        if client is None and logout and uid in self.linked:   # oddiy akkaunt uzilgan holatda: log_out uchun ulaymiz
            row = crud.get_session(uid)
            s = crypto.decrypt(row["session_enc"]) if row else None
            if s:
                try:
                    client = self.factory(s, receive_updates=False)
                    await client.connect()
                except Exception:
                    client = None
        self.linked.discard(uid)
        crud.set_watcher(uid, False)
        self.tg_ids.pop(uid, None)
        self.selected.pop(uid, None)
        if client is not None:
            if logout:
                try:
                    await client.log_out()
                except Exception as e:
                    log.warning("log_out xatosi user=%s: %s", uid, e)
            await self._drop_client(client)
        crud.delete_session(uid)

    async def revoke(self, uid: int, reason: str, client=None):
        """Sessiya o'lgan: bazadan o'chiriladi, haydovchi ogohlantiriladi."""
        log.warning("Sessiya bekor qilindi user=%s: %s", uid, reason)
        self.stop_broadcast(uid)
        c = self.clients.pop(uid, None) or client
        self.linked.discard(uid)
        self.tg_ids.pop(uid, None)
        self.selected.pop(uid, None)
        if c is not None:
            await self._drop_client(c)
        crud.delete_session(uid)
        await self.notify(uid, f"⚠️ {reason}\nRassilka to'xtatildi. Davom etish uchun «🔐 Akkauntni ulash» "
                               "orqali qayta ulaning.")

    async def _drop_client(self, client):
        try:
            await client.disconnect()
        except Exception:
            pass

    async def shutdown(self):
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        for c in list(self.clients.values()):
            await self._drop_client(c)
        self.clients.clear()

    async def notify(self, uid: int, text: str):
        if self.bot is None:
            return
        try:
            await self.bot.send_message(uid, text)
        except TelegramAPIError as e:
            log.info("Haydovchiga xabar yetmadi user=%s: %s", uid, e)


manager = Manager()
