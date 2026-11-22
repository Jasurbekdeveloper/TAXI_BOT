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
import unicodedata

STATUS = {
    "open": "🟢 <b>Lichka ochiq</b> — «💬 Lichkaga yozish»: o'zingiz to'g'ridan-to'g'ri yozasiz",
    "search": "🟡 <b>Username yo'q</b> — «🤖 Bot orqali yozish»: bot mijozni topib, sizning nomingizdan yozadi",
    "phone": "⚪ <b>Faqat telefon</b> orqali bog'laning",
}


_ALLOWED = ((0x20, 0x24F), (0x2B9, 0x2BC), (0x400, 0x4FF), (0x2010, 0x2027), (0x2030, 0x205E), (0x20A0, 0x20CF),
            (0x20E3, 0x20E3), (0x2100, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF), (0x25A0, 0x27BF),
            (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F), (0x1F000, 0x1FAFF))


def _ok(ch: str) -> bool:
    if ch in "\n\t":
        return True
    o = ord(ch)
    return any(a <= o <= b for a, b in _ALLOWED)


def clean_text(s: str | None) -> str:
    """Bezakli/ko'rinmaydigan belgilarni (□□□, fancy shriftlar, yashirin belgilar) olib tashlaydi."""
    out = "".join(ch for ch in unicodedata.normalize("NFKC", s or "") if _ok(ch))   # 𝐀𝐳𝐢𝐳 -> Aziz
    # faqat belgi/emoji qolgan qatorlar («👤 …») — tashlanadi
    out = "\n".join(ln for ln in out.split("\n") if sum(c.isalnum() for c in ln) >= 2 or not ln.strip())
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\.{4,}|…{2,}", "…", out)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", out).strip()


def clean_name(name: str | None, limit: int = 24) -> str | None:
    """Ismni qisqa va o'qiladigan qiladi. Ichida kamida 2 ta harf bo'lmasa (masalan «.» yoki «…») — None."""
    n = re.sub(r"\s+", " ", clean_text(name)).strip(" .·-_|")
    if sum(ch.isalpha() for ch in n) < 2:
        return None
    return n if len(n) <= limit else n[:limit - 1].rstrip() + "…"


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
                order_no=None, user_id=None) -> str:
    e = html.escape
    name = clean_name(name)
    text = clean_text(text)
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
    if user_id:
        lines.append(f"🆔 <code>{int(user_id)}</code>")
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
