"""Xabarni AI'siz tushunish: normalizatsiya, tasniflash, ma'lumot ajratish."""
import re
from dataclasses import dataclass, field

# ---------- Normalizatsiya ----------
CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g'", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ў": "o'",
    "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def normalize(text: str) -> str:
    t = text.lower()
    t = "".join(CYR2LAT.get(ch, ch) for ch in t)
    t = re.sub(r"[ʻʼ‘’`´']", "", t)          # o'/o‘/ўz -> oz (apostrofsiz solishtiramiz)
    t = re.sub(r"[^\w\s+]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------- Kalit so'zlar (apostrofsiz, lotincha) ----------
PASSENGER_KW = {
    "taksi kerak": 3, "taxi kerak": 3, "mashina kerak": 3, "moshina kerak": 3,
    "mashin kerak": 3, "moshin kerak": 3, "kerak taksi": 3, "kerak mashina": 3,
    "taksi bormi": 3, "taxi bormi": 3, "mashina bormi": 3, "moshina bormi": 3,
    "mashin bormi": 3, "moshin bormi": 3, "joy bormi": 3,
    "ketishim kerak": 3, "borishim kerak": 3, "ketish kerak": 2, "kishi bor": 2,
    "odam bor": 2, "kishi bormiz": 2, "odam bormiz": 2, "pochta bor": 2, "yuk bor": 1,
    "ketaman": 2, "ketmoqchiman": 3, "boraman": 2, "bormoqchiman": 3, "kim olib ketadi": 3,
    "pochta jonataman": 3, "pochta jonatish": 3,
    "nujno taksi": 3, "nujna mashina": 3, "nujna taksi": 3, "nujen taksi": 3, "nujno mashinu": 3,
    "nujen voditel": 3, "ishu taksi": 3, "ishu mashinu": 3, "kto edet": 2, "kto poedet": 2,
    "ishu voditelya": 3,
}
DRIVER_KW = {
    "odam olaman": 3, "odam kerak": 3, "yolovchi kerak": 3, "yolovchi olaman": 3,
    "kishi olaman": 3, "pochta olaman": 3, "joy bor": 3, "bosh joy": 3, "bosh joylar": 3,
    "odam bormi": 3, "kishi bormi": 3, "yolovchi bormi": 3, "pochta bormi": 3, "yuk bormi": 3,
    "taksi kerakmi": 3, "taxi kerakmi": 3, "mashina kerakmi": 3, "moshina kerakmi": 3,
    "ketyapman": 2, "ketyapmiz": 2, "ketamiz": 1, "yuramiz": 2, "jonaymiz": 2,
    "nujni passajiri": 3, "beru passajirov": 3, "svobodnie mesta": 3, "est mesta": 3,
    "vozmu passajirov": 3, "edu v": 1, "vizjayu": 2,
    # haydovchi "ketaman/boraman" deb yozib, yo'lovchi chaqiradi: bular yo'lovchi kalitini bosib ketadi
    "kim bor": 3, "kimda bor": 3, "kimga kerak": 3, "kimlar bor": 3, "kim ketadi": 3, "kim boradi": 3,
    "olib ketaman": 3, "olib ketamiz": 3, "olib boraman": 3, "olib boramiz": 3,
    "joy bosh": 3, "joylar bor": 3, "bor joy": 3, "kishi bor joy": 4, "kishilik joy": 3, "orin bor": 3, "bosh orin": 3, "joyimiz bor": 3,
    "yolovchi olamiz": 3, "odam olamiz": 3, "pochta olamiz": 3, "yolovchilar kerak": 3,
    "zakaz olaman": 3, "zakaz olamiz": 3, "dostavka qilamiz": 2,
    # "2 kishi kerak", "ayol kishi bor" — haydovchi yo'lovchi yig'yapti ("kishi bor" yo'lovchi kalitini bosadi)
    "kishi kerak": 3, "yolavchi kerak": 3, "yolavchi olaman": 3, "yolavchi olamiz": 3,
    "ayol kishi bor": 4, "ayol bor": 3, "ayol yolovchi bor": 3, "ayol yolavchi bor": 3, "ayollar bor": 3,
    "pochta ham olamiz": 3, "pochta xam olamiz": 3, "pochta ham olaman": 3, "pochta xam olaman": 3,
    "oldi bosh": 3, "oldi joy bosh": 3, "yolga chiqamiz": 2, "yolga chiqaman": 2,
    # mashina nomlari — kuchsiz belgi
    "cobalt": 1, "kobalt": 1, "gentra": 1, "nexia": 1, "neksiya": 1, "lacetti": 1,
    "malibu": 1, "spark": 1, "damas": 1, "kaptiva": 1, "captiva": 1, "tracker": 1,
}
NEGATED_RE = re.compile(r"\b\w+ kerak(?: emas| mas| yoq)\b|\b\w+ kerakmas\b")
# AI'ga arziydigan xabar belgilari (shahar tilga olinmagan bo'lsa ham)
TAXI_HINT_RE = re.compile(
    r"\b(taksi|taxi|mashin|moshin|pochta|yuk|yolovchi|kishi|odam|joy|ketish|ketam|boram|voditel|passaj|edu|edet)"
)


def _score(text: str, kw: dict) -> int:
    # Oxirida ham \b: "odam bor" kaliti "odam bormi" ga mos kelmasin
    return sum(w for k, w in kw.items() if re.search(rf"\b{re.escape(k)}\b", text))


# ---------- Shaharlar ----------
CITIES = {
    "Toshkent": ["toshkent", "tashkent", "toshken", "tash", "tosh"],
    "Samarqand": ["samarqand", "samarkand", "samarqan", "smq", "sam"],
    "Buxoro": ["buxoro", "buxara", "buxar", "buhara", "buhar", "bukhara", "bukhar"],
    "Andijon": ["andijon", "andijan"],
    "Namangan": ["namangan"],
    "Farg'ona": ["fargona", "fergana", "fargana"],
    "Qo'qon": ["qoqon", "kokand", "koqon"],
    "Marg'ilon": ["margilon", "margilan"],
    "Jizzax": ["jizzax", "djizak", "jizzak", "jizak"],
    "Guliston": ["guliston", "gulistan"],
    "Qarshi": ["qarshi", "karshi"],
    "Shahrisabz": ["shahrisabz", "shaxrisabz"],
    "Termiz": ["termiz", "termez"],
    "Denov": ["denov", "denau"],
    "Surxondaryo": ["surxondaryo", "surxandaryo", "surxandarya", "surxon", "surxan"],
    "Sherobod": ["sherobod", "sherabad", "sherabot", "sherobot"],
    "Muzrabot": ["muzrabot", "muzrabod"],
    "Sho'rchi": ["shorchi", "shurchi"],
    "Boysun": ["boysun", "baysun"],
    "Qumqo'rg'on": ["qumqorgon", "kumkurgan"],
    "Jarqo'rg'on": ["jarqorgon", "jarkurgan"],
    "Sariosiyo": ["sariosiyo", "sariasiya"],
    "Angor": ["angor"],
    "Navoiy": ["navoiy", "navoi"],
    "Urganch": ["urganch", "urgench"],
    "Xiva": ["xiva", "hiva", "khiva"],
    "Nukus": ["nukus"],
    "Chirchiq": ["chirchiq", "chirchik"],
    "Angren": ["angren"],
    "Olmaliq": ["olmaliq", "almalik", "almalyk"],
    "Kattaqo'rg'on": ["kattaqorgon", "kattakurgan"],
    "Bekobod": ["bekobod", "bekabad"],
    "Yangiyo'l": ["yangiyol", "yangiyul"],
    "Yangiyer": ["yangiyer"],
    "Sirdaryo": ["sirdaryo", "sirdarya"],
    "Zarafshon": ["zarafshon", "zarafshan"],
    "Uchquduq": ["uchquduq", "uchkuduk"],
    "Kogon": ["kogon", "kagan"],
    "G'ijduvon": ["gijduvon", "gijduvan"],
    "Kitob": ["kitob", "kitab"],
    "Asaka": ["asaka"],
    "Xonobod": ["xonobod", "xanabad"],
    "Shahrixon": ["shahrixon", "shaxrixon", "shahrixan"],
    "Chust": ["chust"],
    "Rishton": ["rishton", "rishtan"],
    "Qo'ng'irot": ["qongirot", "kungrad"],
}
_ALIAS = sorted(((a, c) for c, al in CITIES.items() for a in al), key=lambda x: -len(x[0]))
CITY_NAMES = set(CITIES)        # kanonik shahar nomlari (ro'yxatga qo'shishda tekshirish uchun)


def known_city(name) -> bool:
    """name tanilgan shaharmi (yoki uning taxallusimi)."""
    return bool(name) and canon_city(name) in CITY_NAMES
FROM_SUFFIX = ("dan", "din", "tan")
TO_SUFFIX = ("ga", "ka", "qa", "gacha")
# Faqat shu qo'shimchalar shahar deb qabul qilinadi: "tashlab", "qarshilik" shahar emas
NEUTRAL_SUFFIX = ("", "a", "u", "e", "ni", "da", "dagi", "ning")
FROM_PREP = ("iz", "s", "ot")
TO_PREP = ("v", "vo", "do", "na")


def canon_city(name):
    """AI yozgan shahar nomini ro'yxatdagi shaklga keltiradi, shunda dedup to'g'ri ishlaydi."""
    if not name:
        return None
    t = normalize(name)
    for alias, city in _ALIAS:
        if t.startswith(alias) and t[len(alias):] in FROM_SUFFIX + TO_SUFFIX + NEUTRAL_SUFFIX:
            return city
    return name


def _city_hits(text: str) -> list[tuple[int, str, str | None]]:
    """Matndagi shaharlar tartib bilan: (pozitsiya, shahar, "from"|"to"|None)."""
    found = []
    prev = ""
    for m in re.finditer(r"\w+", text):
        tok = m.group()
        for alias, city in _ALIAS:
            if tok.startswith(alias):
                rest = tok[len(alias):]
                if rest in FROM_SUFFIX:
                    role = "from"
                elif rest in TO_SUFFIX:
                    role = "to"
                elif rest in NEUTRAL_SUFFIX:    # ruscha "iz X v Y": rol predlogdan olinadi
                    role = "from" if prev in FROM_PREP else "to" if prev in TO_PREP else None
                else:
                    continue                    # boshqa so'z, shahar emas
                found.append((m.start(), city, role))
                break
        prev = tok
    return found


def find_cities(text: str) -> list[str]:
    """Normalizatsiya qilingan matndagi barcha shaharlar, takrorsiz, uchragan tartibida."""
    return list(dict.fromkeys(c for _, c, _ in _city_hits(text)))


def find_route(text: str):
    found = _city_hits(text)
    frm = next((c for _, c, r in found if r == "from"), None)
    to = next((c for _, c, r in found if r == "to"), None)
    rest = [c for _, c, r in found if r is None and c not in (frm, to)]
    if frm is None and rest:
        frm = rest.pop(0)
    if to is None and rest:
        to = rest.pop(0)
    if frm == to:
        to = None
    return frm, to


# ---------- Telefon, kishi soni, vaqt ----------
PHONE_RE = re.compile(r"(?<!\d)(?:\+?998[\s\-]?)?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)")
_NUM_WORDS = {"bir": 1, "ikki": 2, "uch": 3, "tort": 4, "besh": 5, "olti": 6}
SEATS_RE = re.compile(
    r"\b([1-6]|bir|ikki|uch|tort|besh|olti)\s*(?:ta\s*|nafar\s*)?(?:kishi|odam|chel|joy|yolovchi|passaj)"
)
# Oxirida \b emas: "14:00da", "18:30ga" ham o'tsin. Sana (12.11.2026) o'tmasin.
CLOCK_RE = re.compile(r"(?<![\d.:/])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d.:/]*\d)")
SOAT_RE = re.compile(r"\bsoat\s*([01]?\d|2[0-3])(?!\d)")     # "soat 8 da", "soat 9ga"
WORD_TIME_RE = re.compile(
    r"\b(hozir|xozir|bugun|ertaga|indinga|ertalab|kechqurun|kechasi|tushdan keyin|"
    r"seychas|segodnya|zavtra|vecherom|utrom)\b"
)


def find_phone(raw: str):
    for m in PHONE_RE.finditer(raw):
        d = re.sub(r"\D", "", m.group())
        if len(d) == 9:
            d = "998" + d
        if len(d) == 12 and d.startswith("998"):
            return f"+{d[:3]} {d[3:5]} {d[5:8]} {d[8:10]} {d[10:]}"
    return None


def _find_time(raw: str, t: str):
    words = list(dict.fromkeys(WORD_TIME_RE.findall(t)))     # "ertaga ertalab": ikkalasi ham kerak
    clock = CLOCK_RE.search(raw)
    soat = SOAT_RE.search(t)
    hhmm = (f"{clock.group(1).zfill(2)}:{clock.group(2)}" if clock
            else f"{soat.group(1).zfill(2)}:00" if soat else None)
    return " ".join(words + ([hhmm] if hhmm else [])) or None


@dataclass
class Parsed:
    label: str                      # passenger | driver | unknown
    confident: bool
    frm: str | None = None
    to: str | None = None
    seats: int | None = None
    when: str | None = None
    phone: str | None = None
    scores: dict = field(default_factory=dict)


def worth_ai(raw: str, p: Parsed) -> bool:
    return bool(p.frm or p.to or TAXI_HINT_RE.search(normalize(raw)))


# "3 ta joy", "4 joy bo'sh", "2 o'rin" — haydovchi bo'sh joy taklif qilyapti ("joy bormi" esa yo'lovchi so'rovi)
FREE_SEATS_RE = re.compile(r"\b([1-7]|bir|ikki|uch|tort|besh|olti)\s*(?:ta\s*)?(?:joy|orin|mesta|mesto)\b(?!\s*(?:bormi|kerak))")


def analyze(raw: str) -> Parsed:
    t = normalize(raw)
    positive = NEGATED_RE.sub(" ", t)       # "taksi kerak emas" so'rov emas
    p, d = _score(positive, PASSENGER_KW), _score(positive, DRIVER_KW)
    if FREE_SEATS_RE.search(positive):
        d += 2
    if p >= 2 and p >= d + 2:
        label, conf = "passenger", True
    elif d >= 2 and (d >= p + 2 or (d >= 3 and d > p)):
        # kuchli haydovchi belgisi ("kim bor", "joy bor") "ketaman" dan ustun: e'lon maxfiy guruhga tushmasin
        label, conf = "driver", True
    else:
        label, conf = "unknown", False

    frm, to = find_route(t)
    seats = SEATS_RE.search(t)
    n = seats.group(1) if seats else None
    return Parsed(label, conf, frm, to, _NUM_WORDS.get(n, int(n) if n and n.isdigit() else None),
                  _find_time(raw, t), find_phone(raw), {"passenger": p, "driver": d})
