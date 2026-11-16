"""Haydovchi e'lonini qayta ishlab, chiroyli va bir xil ko'rinishga keltiradi.

Masalan:
    SURXONDARYODAN TOSHKENTGA KETAMIZ ERTAGA TERMIZ ANGOR MUZRABOTDAN 3 TA JOY BOR OLDI BOʻSH
    AYOL YOʻLAVCHI BOR TEL +998975990820 TEL +998880534468
->
    🚕 SURXONDARYO ➜ TOSHKENT
    📍 Termiz · Angor · Muzrabot orqali
    🗓 Ertaga
    💺 3 ta bo'sh joy
    ✅ Oldi o'rindiq bo'sh
    👩 Ayol yo'lovchi bor
    📞 +998 97 599 08 20
    📞 +998 88 053 44 68

Avval kalit so'zlar (nlp), keyin AI bo'lsa bo'sh qolgan maydonlar AI bilan to'ldiriladi.
Natija oddiy matn (HTML/markdown belgilarisiz) — userbot uni guruhlarga parse_mode'siz yuboradi.
"""
import re
from dataclasses import dataclass, field

import ai
from nlp import (_NUM_WORDS, CLOCK_RE, FREE_SEATS_RE, PHONE_RE, SEATS_RE, _find_time, canon_city, find_cities,
                 find_route, normalize)

CARS = {
    "cobalt": "Cobalt", "kobalt": "Cobalt", "gentra": "Gentra", "nexia": "Nexia", "neksiya": "Nexia",
    "lacetti": "Lacetti", "laseti": "Lacetti", "malibu": "Malibu", "spark": "Spark", "damas": "Damas",
    "captiva": "Captiva", "kaptiva": "Captiva", "tracker": "Tracker", "onix": "Onix", "monza": "Monza",
    "tahoe": "Tahoe", "equinox": "Equinox", "matiz": "Matiz", "jentra": "Gentra", "kia": "Kia",
    "byd": "BYD", "chery": "Chery", "haval": "Haval", "sonata": "Sonata", "camry": "Camry", "kamri": "Camry",
}
FLAGS = {
    "pochta": re.compile(r"\b(pochta|posilk\w*|yuk olamiz|yuk olaman)\b"),
    "ayol": re.compile(r"\bayol(lar)?\b"),
    "oldi_bosh": re.compile(r"\boldi (joy |orindiq )?bosh\b|\boldingi orindiq\b"),
    "konditsioner": re.compile(r"\b(konditsioner|kondisioner|kondisaner|konditsaner|kondi)\b"),
    "bagaj": re.compile(r"\b(bagaj|bagaz|yukxona|bagajnik)\b"),
}
FLAG_TEXT = {
    "oldi_bosh": "✅ Oldi o'rindiq bo'sh",
    "ayol": "👩 Ayol yo'lovchi bor",
    "pochta": "📦 Pochta ham olamiz",
    "konditsioner": "❄️ Konditsioner bor",
    "bagaj": "🧳 Bagaj joyi bor",
}
# normalize() dan keyin qidiriladi (kirill -> lotin, apostrofsiz): "250 минг" -> "250 ming"
PRICE_RE = re.compile(r"\b(\d{2,3}(?:[ .]?\d{3})?)\s*(ming|mln|som|sum|tis|tisyach|rubl)\b")


@dataclass
class AdInfo:
    frm: str | None = None
    to: str | None = None
    stops: list[str] = field(default_factory=list)
    when: str | None = None
    seats: int | None = None
    car: str | None = None
    price: str | None = None
    phones: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)

    @property
    def useful(self) -> bool:
        """Formatlash ma'noga egami: kamida yo'nalishning bir tomoni yoki telefon bor."""
        return bool(self.frm or self.to) and bool(self.phones or self.seats or self.when or self.stops)


def _phones(raw: str) -> list[str]:
    out = []
    for m in PHONE_RE.finditer(raw):
        d = re.sub(r"\D", "", m.group())
        if len(d) == 9:
            d = "998" + d
        if len(d) == 12 and d.startswith("998"):
            out.append(f"+{d[:3]} {d[3:5]} {d[5:8]} {d[8:10]} {d[10:]}")
    return list(dict.fromkeys(out))


def extract(raw: str) -> AdInfo:
    """Kalit so'zlar asosida (AI'siz)."""
    t = normalize(raw)
    frm, to = find_route(t)
    stops = [c for c in find_cities(t) if c not in (frm, to)]
    seat_m = FREE_SEATS_RE.search(t) or SEATS_RE.search(t)
    seats = None
    if seat_m:
        n = seat_m.group(1)
        seats = _NUM_WORDS.get(n, int(n) if n.isdigit() else None)
    car = next((v for k, v in CARS.items() if re.search(rf"\b{k}\b", t)), None)
    price_m = PRICE_RE.search(t)
    return AdInfo(frm=frm, to=to, stops=stops, when=_find_time(raw, t), seats=seats, car=car,
                  price=f"{price_m.group(1)} {price_m.group(2)}" if price_m else None, phones=_phones(raw),
                  flags={k for k, rx in FLAGS.items() if rx.search(t)})


def merge_ai(info: AdInfo, d: dict | None) -> AdInfo:
    """AI faqat bo'sh qolgan maydonlarni to'ldiradi — kalit so'z natijasi ustun (AI to'qishi mumkin)."""
    if not d:
        return info
    info.frm = info.frm or canon_city(d.get("from"))
    info.to = info.to or canon_city(d.get("to"))
    if info.frm == info.to:
        info.to = None
    if not info.stops:
        info.stops = [canon_city(s) or s for s in d.get("stops", []) if canon_city(s) not in (info.frm, info.to)]
    info.when = info.when or d.get("time")
    info.seats = info.seats or d.get("seats")
    info.car = info.car or d.get("car")
    info.price = info.price or d.get("price")
    if not info.phones:                     # AI bergan raqam ham formatdan o'tadi, to'qilgani tushib qoladi
        info.phones = _phones(" ".join(d.get("phones", [])))
    info.flags |= {k for k in FLAG_TEXT if d.get(k)}
    return info


def _cap(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def render(info: AdInfo) -> str:
    route = " ➜ ".join(x.upper() for x in (info.frm, info.to) if x)
    lines = [f"🚕 {route}"]
    if info.stops:
        lines.append("📍 " + " · ".join(info.stops) + " orqali")
    if info.when:
        icon = "🕕" if CLOCK_RE.search(info.when) else "🗓"
        lines.append(f"{icon} {_cap(info.when)}")
    if info.seats:
        lines.append(f"💺 {info.seats} ta bo'sh joy")
    if info.car:
        lines.append(f"🚗 {info.car}")
    for k in ("oldi_bosh", "ayol", "pochta", "konditsioner", "bagaj"):
        if k in info.flags:
            lines.append(FLAG_TEXT[k])
    if info.price:
        lines.append(f"💰 {info.price}")
    lines += [f"📞 {p}" for p in info.phones]
    return "\n".join(lines)


async def build(raw: str, use_ai: bool = True) -> tuple[str | None, AdInfo]:
    """(formatlangan matn yoki None, ajratilgan ma'lumot). Ma'lumot yetarli bo'lmasa None."""
    info = extract(raw)
    missing = not (info.frm and info.to) or not info.phones
    if use_ai and missing:
        info = merge_ai(info, await ai.extract_ad(raw))
    return (render(info) if info.useful else None), info
