"""Donor (maxfiy/yopiq) guruhlar parseri.

Texnik userbot (MODE=both, main.run_userbot) yoki shu guruhga a'zo haydovchi akkaunti (services/broadcaster)
donor guruhdan yangi xabar olganda handle() chaqiriladi. Xabardan ajratiladi:
  • matn — reklama, kanal havolalari, @username, hashtag va "User ID" qatorlaridan tozalangan e'lon;
  • yashirin havolalar — matn ichidagi text_link (MessageEntityTextUrl), foydalanuvchi eslatmasi
    (MessageEntityMentionName) va inline tugmalar (KeyboardButtonUrl / KeyboardButtonUserProfile);
  • mijoz — tg://user?id=..., "User ID: 123", "Mijoz: @username", lichka tugmasidagi t.me/username
    yoki xabarni oddiy foydalanuvchi o'zi yozgan bo'lsa — yuboruvchining id/username i;
  • telefon raqami.
Haydovchi e'loni (nlp/AI "driver") uzatilmaydi. Natija services.order_dispatcher ga beriladi.
Telethon obyektlari "duck typing" bilan o'qiladi (testlarda soddalashtirilgan obyektlar ishlatiladi).
"""
import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field

import routes
from database import crud
from nlp import analyze, find_phone, fmt_phone, is_spam, tidy

log = logging.getLogger(__name__)

TG_USER_RE = re.compile(r"tg://(?:user\?id|openmessage\?user_id)=(\d+)", re.I)
TEXT_ID_RE = re.compile(r"(?:user\s*_?id|юзер\s*id|айди|\bid)\s*[:：#=]?\s*(\d{5,})", re.I)
TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})(?:[/?#].*)?$", re.I)
# tg://resolve?domain=username  (lichka tugmasi ko'pincha shu ko'rinishda bo'ladi)
TG_RESOLVE_RE = re.compile(r"tg://resolve\?domain=([A-Za-z][A-Za-z0-9_]{3,31})", re.I)
URL_RE = re.compile(r"(?:https?://|tg://|www\.)\S+|\b(?:t\.me|telegram\.me)/\S+", re.I)
MENTION_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{3,31}")
HASHTAG_RE = re.compile(r"#\w+")
ID_LINE_RE = re.compile(r"^\W*(?:user\s*_?id|юзер\s*id|айди|id)\b.*$", re.I)
# Mijoz lichkasiga olib boruvchi tugma/havola yozuvlari
CLIENT_HINT_RE = re.compile(r"лич|ёз|ез|yoz|profil|профил|mijoz|клиент|kli[ey]nt|aloqa|bog'?lan|контакт|написат|"
                            r"lichka|user|odam|yo'?lovchi|passaj", re.I)
CLIENT_MENTION_RE = re.compile(r"(?:mijoz|клиент|kli[ey]nt|lichka|личка|profil|aloqa|yo'?lovchi)\W{0,4}"
                               r"@([A-Za-z][A-Za-z0-9_]{3,31})", re.I)
# Reklama/xizmat qatorlari: e'londan butunlay olib tashlanadi
AD_LINE_RE = re.compile(r"obuna|подпиш|kanal(?:imiz|ga)|канал|reklama|реклам|admin\s*:|админ|"
                        r"guruhga qo'?shil|join|bot orqali|бот орқали|заказ через", re.I)
RESERVED_TME = {"joinchat", "addlist", "c", "s", "share", "iv", "proxy", "socks", "addstickers", "addemoji",
                "setlanguage", "boost", "contact", "m"}
MAX_TEXT = 600


@dataclass
class DonorOrder:
    chat_id: int
    msg_id: int
    text: str                                   # tozalangan e'lon
    raw: str
    user_id: int | None = None
    username: str | None = None
    phone: str | None = None
    urls: list[str] = field(default_factory=list)
    frm: str | None = None
    to: str | None = None
    btn_url: str | None = None                   # donor xabaridagi «Клиент личкаси» tugmasining asl URL'i
    source_title: str | None = None              # qaysi donor guruhdan olingani

    @property
    def link(self) -> str | None:
        if self.username:
            return f"https://t.me/{self.username}"
        if self.btn_url:                         # donor tugmasining asl havolasi (ko'pincha ishlaydi)
            return self.btn_url
        if self.user_id:
            return f"tg://user?id={self.user_id}"
        return None

    @property
    def source_url(self) -> str | None:
        """Asl xabarga havola (donor guruh a'zolari uchun ochiladi; «🔗 Xabarga o'tish» tugmasi)."""
        s = str(self.chat_id)
        if s.startswith("-100") and self.msg_id:
            return f"https://t.me/c/{s[4:]}/{self.msg_id}"
        return None

    def dedup_keys(self) -> list[str]:
        keys = []
        if self.user_id:
            keys.append(f"uid:{self.user_id}")
        if self.username:
            keys.append(f"un:{self.username.lower()}")
        if self.phone:
            keys.append("ph:" + re.sub(r"\D", "", self.phone))
        return keys


# ---------- ajratish ----------
def _slice16(text: str, offset: int, length: int) -> str:
    """Telegram entity offsetlari UTF-16 birligida (emoji 2 birlik)."""
    b = text.encode("utf-16-le")
    return b[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def _url_username(url: str) -> str | None:
    """t.me/username yoki tg://resolve?domain=username dan mijoz username'ini ajratadi."""
    u = (url or "").strip()
    m = TME_RE.match(u) or TG_RESOLVE_RE.search(u)
    if not m:
        return None
    name = m.group(1)
    if name.lower() in RESERVED_TME or name.lower().endswith("bot"):
        return None
    return name


_tme_username = _url_username          # eski nom (moslik uchun)


def collect_links(message) -> list[tuple[str, str | None, int | None]]:
    """[(yozuv, url, user_id)] — matndagi yashirin havolalar va inline tugmalar."""
    text = getattr(message, "message", None) or getattr(message, "raw_text", "") or ""
    out = []
    for ent in getattr(message, "entities", None) or []:
        url = getattr(ent, "url", None)                     # MessageEntityTextUrl (text_link)
        uid = getattr(ent, "user_id", None)                 # MessageEntityMentionName (text_mention)
        if url or uid:
            out.append((_slice16(text, getattr(ent, "offset", 0), getattr(ent, "length", 0)), url, uid))
    markup = getattr(message, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for btn in getattr(row, "buttons", None) or []:
            url = getattr(btn, "url", None)                 # KeyboardButtonUrl
            uid = getattr(btn, "user_id", None)             # KeyboardButtonUserProfile
            if url or uid:
                out.append((getattr(btn, "text", "") or "", url, uid))
    return out


def clean_text(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        if ID_LINE_RE.match(ln) or AD_LINE_RE.search(ln):
            continue
        ln = URL_RE.sub(" ", ln)
        ln = MENTION_RE.sub(" ", ln)
        ln = HASHTAG_RE.sub(" ", ln)
        ln = re.sub(r"\s{2,}", " ", ln).strip(" -|•·:—")
        if re.search(r"\w", ln):
            lines.append(ln)
    out = "\n".join(lines)
    return out[:MAX_TEXT] + ("…" if len(out) > MAX_TEXT else "")


def extract(message, chat_id: int, sender=None) -> DonorOrder:
    raw = getattr(message, "message", None) or getattr(message, "raw_text", "") or ""
    links = collect_links(message)
    urls = [u for _, u, _ in links if u]
    user_id = username = None

    # 1) tg://user?id=..., foydalanuvchi eslatmasi, profil tugmasi
    for label, url, uid in links:
        m = TG_USER_RE.search(url or "")
        if uid or m:
            user_id = int(uid or m.group(1))
            break
    if user_id is None:
        m = TG_USER_RE.search(raw)
        if m:
            user_id = int(m.group(1))
    # 2) matnda "User ID: 12345678"
    if user_id is None:
        m = TEXT_ID_RE.search(raw)
        if m:
            user_id = int(m.group(1))
    # 3) "Mijoz: @username" yoki lichka tugmasi/havolasidagi t.me/username
    m = CLIENT_MENTION_RE.search(raw)
    if m:
        username = m.group(1)
    btn_url = None
    if username is None:
        for label, url, _ in links:
            name = _tme_username(url or "")
            if name and CLIENT_HINT_RE.search(label or ""):
                username = name
                break
    # Lichka tugmasining asl URL'i (username bo'lmasa — shuni o'zi uzatiladi, donor tugmasi kabi ishlashi uchun)
    if username is None:
        for label, url, _ in links:
            if url and CLIENT_HINT_RE.search(label or "") and url.startswith(("tg://", "http")):
                btn_url = url
                break
    # 4) xabarni oddiy foydalanuvchining o'zi yozgan bo'lsa
    if user_id is None and username is None and sender is not None and not getattr(sender, "bot", False) \
            and getattr(sender, "first_name", None) is not None:          # kanal/guruh nomidan emas
        user_id = getattr(sender, "id", None)
        username = getattr(sender, "username", None)

    p = analyze(raw)
    # User ID (9–10 raqam) telefon deb olinmasin: "User ID: 883388291" -> "+998 88 338 82 91" xatosi
    ph_src = re.sub(rf"(?<!\d){user_id}(?!\d)", " ", raw) if user_id else raw
    ph_src = "\n".join(ln for ln in ph_src.splitlines() if not ID_LINE_RE.match(ln))
    phone = find_phone(ph_src) or fmt_phone(getattr(sender, "phone", None))     # matnda yo'q bo'lsa profil raqami
    text = tidy(raw) or clean_text(raw)      # "o'z formatimizga": imzo/reklama/telefon/emoji devori tozalanadi
    return DonorOrder(chat_id=chat_id, msg_id=getattr(message, "id", 0), text=text, raw=raw,
                      user_id=user_id, username=username, phone=phone, urls=urls, frm=p.frm, to=p.to,
                      btn_url=btn_url)


# ---------- donor ro'yxati (kesh) ----------
_donors: dict[int, object] | None = None
_seen: OrderedDict = OrderedDict()          # (chat_id, msg_id): bir xabarni bir nechta akkaunt ko'rsa bir marta


def reload():
    global _donors
    _donors = {r["chat_id"]: r for r in crud.all_donors()}


def donors() -> dict:
    if _donors is None:
        reload()
    return _donors


def is_donor(chat_id) -> bool:
    d = donors().get(chat_id)
    return bool(d and d["enabled"])


async def _resolve_username(event, user_id):
    """userbot (donor guruh a'zosi) user_id dan @username ni aniqlaydi (mijozda bo'lsa). Best-effort.
    access_hash akkauntga bog'liq — haydovchiga ko'chmaydi; lekin username bo'lsa havola hamma uchun ishlaydi.
    Donor xabarida mijoz «min» (bot ishorasi) bo'lsa, oddiy get_entity(id) ishlamaydi — shuning uchun
    xabar kontekstida (InputPeerUserFromMessage) ham sinab ko'ramiz."""
    client = getattr(event, "client", None)
    if client is None or not user_id:
        return None
    # 1) to'g'ridan-to'g'ri (akkaunt mijoz bilan umumiy chatda bo'lsa)
    try:
        ent = await client.get_entity(user_id)
        if getattr(ent, "username", None):
            return ent.username
    except Exception:
        pass
    # 2) Xabarni xom so'rov bilan qayta olamiz: «Клиент личкаси» profil tugmasi (KeyboardButtonUserProfile)
    #    bo'lsa, Telegram mijozni javobning users ro'yxatida username'i bilan birga yuboradi
    try:
        from telethon.tl.functions.channels import GetMessagesRequest as ChGetMessages
        from telethon.tl.functions.messages import GetMessagesRequest
        from telethon.tl.types import InputMessageID, InputPeerChannel
        msg = getattr(event, "message", None)
        msg_id = getattr(msg, "id", None) or getattr(event, "id", None)
        if msg_id:
            peer = await client.get_input_entity(event.chat_id)
            if isinstance(peer, InputPeerChannel):
                res = await client(ChGetMessages(channel=peer, id=[InputMessageID(msg_id)]))
            else:
                res = await client(GetMessagesRequest(id=[InputMessageID(msg_id)]))
            for u in getattr(res, "users", None) or []:
                if u.id == user_id:
                    name = getattr(u, "username", None) or next(
                        (x.username for x in (getattr(u, "usernames", None) or []) if getattr(x, "active", False)), None)
                    if name:
                        return name
    except Exception as e:
        log.info("[donor] xabar orqali username olinmadi (uid=%s): %s", user_id, str(e)[:90])
    # 3) «min-user»: mijoz shu xabarda ishora (mention) qilingan — xabarni kontekst qilib aniqlaymiz
    try:
        from telethon.tl.functions.users import GetUsersRequest
        from telethon.tl.types import InputUserFromMessage
        msg = getattr(event, "message", None)
        msg_id = getattr(msg, "id", None) or getattr(event, "id", None)
        if msg_id:
            peer = await client.get_input_entity(event.chat_id)
            ref = InputUserFromMessage(peer=peer, msg_id=msg_id, user_id=user_id)
            res = await client(GetUsersRequest([ref]))
            if res:
                return getattr(res[0], "username", None)
    except Exception as e:
        log.info("[donor] username aniqlanmadi (uid=%s): %s", user_id, str(e)[:90])
    return None


async def _refetch_with_buttons(event, message, waits=(2, 4)):
    client = getattr(event, "client", None)
    msg_id = getattr(message, "id", None)
    if client is None or not msg_id:
        return message
    for w in waits:
        await asyncio.sleep(w)
        try:
            fresh = await client.get_messages(event.chat_id, ids=msg_id)
        except Exception as e:
            log.info("[donor] qayta o'qib bo'lmadi: %s", str(e)[:90])
            return message
        if fresh is not None and collect_links(fresh):
            log.info("[donor] tugma keyinroq qo'shilgan ekan — qayta o'qildi (%s s)", w)
            return fresh
    return message


# ---------- asosiy oqim ----------
async def handle(event, exclude_sender_ids=()) -> str:
    """Donor guruh xabari. Natija: 'sent', 'dup', 'driver', 'empty', 'no_contact', 'seen', 'skip'."""
    chat_id = event.chat_id
    if not is_donor(chat_id) or chat_id in routes.closed_chat_ids():
        return "skip"
    key = (chat_id, event.id)
    if key in _seen:
        return "seen"
    _seen[key] = True
    while len(_seen) > 5000:
        _seen.popitem(last=False)
    if event.sender_id in exclude_sender_ids:            # ulangan haydovchi akkauntining o'z xabari
        return "skip"
    message = getattr(event, "message", event)
    raw = getattr(message, "message", None) or getattr(event, "raw_text", "") or ""
    if not raw.strip():
        return "empty"
    try:
        sender = await event.get_sender()
    except Exception:
        sender = None

    from pipeline import decide, stats
    if is_spam(raw):                                     # reklama / bot taklifi / "feyk xabar"
        stats["donor_skipped"] += 1
        log.info("[donor] spam o'tkazildi | %s", raw[:60].replace("\n", " "))
        return "spam"
    p = analyze(raw)
    label, src, _ = await decide(raw, p)
    if label == "driver":                                # haydovchi e'loni yopiq guruhga tushmaydi
        stats["donor_skipped"] += 1
        log.info("[donor] haydovchi e'loni o'tkazildi (%s) | %s", src, raw[:60].replace("\n", " "))
        return "driver"
    if label != "passenger" and not (p.frm or p.to):     # taksi e'loni emas (reklama/boshqa): shahar/yo'nalish yo'q
        stats["donor_skipped"] += 1
        log.info("[donor] taksi e'loni emas, o'tkazildi | %s", raw[:60].replace("\n", " "))
        return "noroute"

    if not collect_links(message):
        # Ko'p donor botlar avval matnni yuboradi, «Клиент личкаси» tugmasini esa keyinroq (edit bilan) qo'shadi.
        # NewMessage paytida tugma hali yo'q (log: btn=None urls=[]) — biroz kutib xabarni qayta o'qiymiz.
        message = await _refetch_with_buttons(event, message)
    order = extract(message, chat_id, sender)
    if order.user_id and not order.username:             # username bo'lmasa — userbot orqali aniqlab ko'ramiz (link chiqsin)
        un = await _resolve_username(event, order.user_id)
        if un:
            order.username = un
    # Diagnostika: donor qanday kontakt havolasi berganini ko'rsatadi (link chiqmasa sababini bilish uchun).
    # mention=True — mijoz xabarda haqiqiy ishora (MentionName) bilan; min-user aniqlash shunda mumkin.
    ents = getattr(message, "entities", None) or []
    mention = any(getattr(e, "user_id", None) for e in ents)
    markup = getattr(message, "reply_markup", None)
    btn_types = [type(b).__name__ for row in (getattr(markup, "rows", None) or []) for b in (row.buttons or [])]
    log.info("[donor] kontakt | uid=%s un=%s mention=%s btn=%s link=%s urls=%s markup=%s btns=%s",
             order.user_id, order.username, mention, order.btn_url, order.link, order.urls[:4],
             type(markup).__name__ if markup is not None else None, btn_types[:4])
    if not order.text or not (order.link or order.phone):
        stats["donor_skipped"] += 1
        return "no_contact"
    from services import order_dispatcher
    return await order_dispatcher.dispatch(order, donors()[chat_id])
