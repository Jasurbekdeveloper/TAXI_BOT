"""Yopiq guruhga yuboriladigan YAGONA e'lon formati — oddiy guruh, haydovchi guruhi va donor uchun bir xil.

🧍 YO'LOVCHI
📍 Toshkent → Samarqand
🕕 bugun 18:00 · 👥 2 kishi
📞 +998901234567                (matndagi raqam)
📱 +998901234567 · profildan    (matnda bo'lmasa, Telegram profilidagi raqam)
👤 Ism · @username
🟢 Lichka ochiq                 (aloqa holati — pastdagi STATUS)
💬 matn
🔗 Manba guruh
#Toshkent_Samarqand #Order_15

Tugmalar: [✅ Oldim] [💬 Yozish]  /  [🔗 Xabarga o'tish]
"""
import html
import re

STATUS = {
    "open": "🟢 <b>Lichka ochiq</b> — «💬 Lichkaga yozish»: o'zingiz to'g'ridan-to'g'ri yozasiz",
    "search": "🟡 <b>Username yo'q</b> — «🤖 Bot orqali yozish»: bot mijozni topib, sizning nomingizdan yozadi",
    "phone": "⚪ <b>Faqat telefon</b> orqali bog'laning",
}


def _tag(s) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s or "")


def hashtags(frm, to, order_no=None) -> str:
    a, b = _tag(frm), _tag(to)
    tags = []
    if a and b:
        tags.append(f"#{a}_{b}")
    elif a or b:
        tags.append(f"#{a or b}")
    if order_no:
        tags.append(f"#Order_{order_no}")
    return " ".join(tags)


def contact_status(username, order_no) -> str:
    if username:
        return "open"
    if order_no:
        return "search"
    return "phone"


def _tel(p) -> str:
    return re.sub(r"[^\d+]", "", str(p or ""))      # bo'shliqsiz — Telegram bosiladigan qiladi


def render_card(*, frm=None, to=None, when=None, seats=None, text_phone=None, profile_phone=None,
                name=None, username=None, text="", source_title=None, source_url=None,
                order_no=None) -> str:
    e = html.escape
    lines = ["🧍 <b>YO'LOVCHI</b>"]
    if frm or to:
        lines.append("📍 " + " → ".join(e(x) for x in (frm, to) if x) if frm and to
                     else f"📍 {e(frm)} →" if frm else f"📍 → {e(to)}")
    meta = [f"🕕 {e(str(when))}" if when else "", f"👥 {seats} kishi" if seats else ""]
    if any(meta):
        lines.append(" · ".join(x for x in meta if x))
    if text_phone:
        lines.append(f"📞 {e(_tel(text_phone))}")
    if profile_phone and _tel(profile_phone) != _tel(text_phone):
        lines.append(f"📱 {e(_tel(profile_phone))} · <i>Telegram profilidan</i>")
    who = " · ".join(x for x in (e(name) if name else "", f"@{e(username)}" if username else "") if x)
    if who:
        lines.append(f"👤 {who}")
    lines.append(STATUS[contact_status(username, order_no)])
    if text:
        lines.append(f"\n💬 <i>{e(text[:400])}</i>")
    if source_title:
        lines.append(f'🔗 <a href="{e(source_url, quote=True)}">{e(source_title)}</a>' if source_url
                     else f"🔗 {e(source_title)}")
    tags = hashtags(frm, to, order_no)
    if tags:
        lines.append(tags)
    return "\n".join(lines)
