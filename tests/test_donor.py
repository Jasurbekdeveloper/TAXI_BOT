"""Donor parser: yashirin havolalar, inline tugmalar, User ID, matn tozalash, dublikat va uzatish."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def ent_url(text, part, url):
    """text ichidagi part uchun MessageEntityTextUrl (UTF-16 offset)."""
    i = text.index(part)
    off = len(text[:i].encode("utf-16-le")) // 2
    return NS(offset=off, length=len(part.encode("utf-16-le")) // 2, url=url)


def msg(text, entities=None, buttons=None, mid=1):
    rows = [NS(buttons=[NS(**b) for b in row]) for row in (buttons or [])]
    return NS(message=text, entities=entities or [], reply_markup=NS(rows=rows) if rows else None, id=mid)


def test_text_link_tg_user():
    from services.donor_parser import extract
    t = "🚖 Denovdan Samarqand ketish qancha bo'lyapti\nКлиент личкаси"
    o = extract(msg(t, [ent_url(t, "Клиент личкаси", "tg://user?id=5551234")]), -100500)
    assert o.user_id == 5551234 and o.link == "tg://user?id=5551234"
    assert o.frm == "Denov" and o.to == "Samarqand"
    assert o.text == "🚖 Denovdan Samarqand ketish qancha bo'lyapti"   # "Клиент личкаси" xizmat qatori tozalandi


def test_inline_button_username_and_cleanup():
    from services.donor_parser import extract
    t = ("Termizdan Toshkentga 2 kishi kerak\nTel: 90 123 45 67\n#Termiz_Toshkent\n"
         "📢 Kanalimizga obuna bo'ling @taksi_kanal\nhttps://t.me/taksi_kanal")
    o = extract(msg(t, buttons=[[{"text": "📢 Kanal", "url": "https://t.me/taksi_kanal"}],
                               [{"text": "👤 Mijoz lichkasi", "url": "https://t.me/ali_client"}]]), -100500)
    assert o.username == "ali_client" and o.user_id is None and o.link == "https://t.me/ali_client"
    assert o.phone == "+998 90 123 45 67"
    assert o.text == "Termizdan Toshkentga 2 kishi kerak"   # reklama, hashtag, link, telefon qatori tozalandi
    assert "https://t.me/taksi_kanal" in o.urls and "https://t.me/ali_client" in o.urls


def test_user_id_in_text_and_profile_button():
    from services.donor_parser import extract
    o = extract(msg("Toshkentga taksi kerak\nUser ID: 77889900"), -1)
    assert o.user_id == 77889900 and "User ID" not in o.text
    o = extract(msg("Buxoroga taksi kerak", buttons=[[{"text": "Profil", "user_id": 4242}]]), -1)
    assert o.user_id == 4242
    o = extract(msg("Mijoz: @vali_aka Samarqandga 1 kishi"), -1)
    assert o.username == "vali_aka"


def test_plain_user_sender_and_bot_sender():
    from services.donor_parser import extract
    user = NS(id=999, username="oddiy_user", first_name="Ali", bot=False)
    o = extract(msg("Andijonga taksi kerak"), -1, sender=user)
    assert (o.user_id, o.username) == (999, "oddiy_user")
    bot = NS(id=1, username="aggregator_bot", first_name="Agg", bot=True)
    assert extract(msg("Andijonga taksi kerak"), -1, sender=bot).user_id is None      # bot — mijoz emas
    chan = NS(id=-100777, username="kanal", title="Kanal")                              # kanal nomidan
    assert extract(msg("Andijonga taksi kerak"), -1, sender=chan).user_id is None


def test_profile_phone_fallback():
    from services.donor_parser import extract
    # matnda raqam yo'q, lekin muallif profilida raqami ochiq -> profil raqami ko'rsatiladi
    pub = NS(id=555, username=None, first_name="Ali", bot=False, phone="998901234567")
    assert extract(msg("Toshkentga odam bor, ketadi"), -1, sender=pub).phone == "+998 90 123 45 67"
    # matnda raqam bo'lsa — matndagisi ustun
    assert extract(msg("Toshkentga odam bor +998937778899"), -1, sender=pub).phone == "+998 93 777 88 99"
    # profil raqami yashirin (None) — qo'shilmaydi
    hidden = NS(id=556, username=None, first_name="Vali", bot=False, phone=None)
    assert extract(msg("Toshkentga odam bor, ketadi"), -1, sender=hidden).phone is None


def test_client_button_url_preserved():
    from services.donor_parser import extract
    # username yo'q: «Клиент личкаси» tugmasining ASL URL'i uzatiladi (donor tugmasi kabi ishlashi uchun)
    o = extract(msg("Samarqandga taksi kerak",
                    buttons=[[{"text": "👤 Клиент личкаси", "url": "tg://openmessage?user_id=7982067161"}]]), -100500)
    assert o.username is None and o.btn_url == "tg://openmessage?user_id=7982067161"
    assert o.link == "tg://openmessage?user_id=7982067161"      # qayta qurilgan tg://user emas, asl havola
    # t.me/username tugmasi bo'lsa — username ustun (ishonchli havola)
    o2 = extract(msg("Buxoroga taksi kerak",
                     buttons=[[{"text": "Mijoz lichkasi", "url": "https://t.me/ali_client"}]]), -100500)
    assert o2.username == "ali_client" and o2.link == "https://t.me/ali_client"


def test_channel_link_not_taken_as_client():
    from services.donor_parser import extract
    o = extract(msg("Toshkentga taksi kerak", buttons=[[{"text": "Kanalimiz", "url": "https://t.me/zakaz_kanal"}],
                                                       [{"text": "Bot", "url": "https://t.me/taxi_order_bot"}]]), -1)
    assert o.username is None and o.user_id is None


@pytest.fixture
def env(tmp_path, monkeypatch):
    from database import crud, models
    import pipeline
    from services import donor_parser
    models.close()
    for k, v in (("DB_FILE", "t.db"), ("USERS_FILE", "u.json"), ("ROUTES_FILE", "r.json")):
        monkeypatch.setattr(config, k, tmp_path / v)
    monkeypatch.setattr(config, "DRIVERS_CHAT_ID", -1009999)
    monkeypatch.setattr(config, "AI_API_KEY", "")
    monkeypatch.setattr(config, "DONOR_DEDUP_MINUTES", 30)
    while not pipeline.queue.empty():
        pipeline.queue.get_nowait()
    donor_parser._seen.clear()
    crud.add_donor(-100500, "Donor A")
    donor_parser.reload()
    yield NS(crud=crud, q=pipeline.queue, dp=donor_parser)
    models.close()
    donor_parser._donors = None


def event(text, mid, entities=None, buttons=None, sender=None, chat=-100500, sender_id=None):
    m = msg(text, entities, buttons, mid)

    async def gs():
        return sender
    return NS(chat_id=chat, id=mid, message=m, raw_text=text, sender_id=sender_id, get_sender=gs)


def test_handle_dispatch_dedup_and_driver_skip(env):
    t = "Denovdan Samarqandga taksi kerak 2 kishi\nКлиент личкаси"
    e1 = event(t, 1, [ent_url(t, "Клиент личкаси", "tg://user?id=5551234")])
    assert asyncio.run(env.dp.handle(e1)) == "sent"
    item = env.q.get_nowait()
    assert item.chat_id == -1009999 and item.style == "donor" and item.contact_url == "tg://user?id=5551234"
    assert item.source_url == "https://t.me/c/500/1"           # asl xabarga havola (Manba)
    assert "Yangi mijoz aniqlandi!" in item.text and "<code>5551234</code>" in item.text
    assert '<a href="tg://user?id=5551234">Клиент личкаси</a>' in item.text and "#Denov_Samarqand" in item.text
    assert "Manba" not in item.text                            # xunuk chat_id qatori yo'q (tugma yetarli)
    assert asyncio.run(env.dp.handle(e1)) == "seen"                     # bir xabarni ikki akkaunt ko'rdi
    e2 = event("Yana Denovdan taksi kerak", 2, buttons=[[{"text": "Lichka", "url": "tg://user?id=5551234"}]])
    assert asyncio.run(env.dp.handle(e2)) == "dup"                      # 30 daqiqa ichida shu User ID
    e3 = event("Ertaga ertalab Toshkentga ketamz odam poshta olamz +998998269111", 3)
    assert asyncio.run(env.dp.handle(e3)) == "driver"                   # haydovchi e'loni uzatilmaydi
    e4 = event("Toshkentga taksi kerak", 4, chat=-100600)
    assert asyncio.run(env.dp.handle(e4)) == "skip"                     # donor emas
    e5 = event("Toshkentga taksi kerak", 5)
    assert asyncio.run(env.dp.handle(e5)) == "no_contact"               # mijozga bog'lanish yo'li yo'q
    assert env.q.empty() and env.crud.get_donor(-100500)["forwarded"] == 1


def test_handle_resolves_username_via_userbot(env):
    # matnda @username yo'q, lekin userbot (donor a'zosi) user_id dan @username topadi -> ishlaydigan havola
    class FakeClient:
        async def get_entity(self, uid):
            assert uid == 7982067161
            return NS(username="topildi_user")
    ev = event("Samarqandga taksi kerak User ID: 7982067161", 30)
    ev.client = FakeClient()
    assert asyncio.run(env.dp.handle(ev)) == "sent"
    item = env.q.get_nowait()
    assert item.contact_url == "https://t.me/topildi_user" and "@topildi_user" in item.text


def test_handle_skips_non_taxi(env):
    # reklama (jalyuzi) -> spam; shahar/yo'nalishsiz begona xabar -> noroute. Ikkalasi ham uzatilmaydi
    assert asyncio.run(env.dp.handle(
        event("🔲 JALYUZI ishlab chiqaruvchidan fabrika narxida +998997640057", 40))) == "spam"
    assert asyncio.run(env.dp.handle(
        event("Assalomu alaykum hammaga, qalay ahvollar +998901112233", 41))) == "noroute"
    assert env.q.empty()


def test_donor_target_and_disable(env):
    from services.donor_parser import reload
    env.crud.set_donor_target(-100500, -100777, "Yopiq B")
    reload()
    assert asyncio.run(env.dp.handle(event("Buxoroga taksi kerak +998901112233", 10))) == "sent"
    assert env.q.get_nowait().chat_id == -100777
    env.crud.set_donor_enabled(-100500, False)
    reload()
    assert asyncio.run(env.dp.handle(event("Buxoroga taksi kerak +998901112244", 11))) == "skip"


def test_failed_delivery_releases_dedup(env):
    import pipeline
    asyncio.run(env.dp.handle(event("Navoiyga taksi kerak +998901110000", 20)))
    item = env.q.get_nowait()
    assert env.crud.seen_recently(item.undo_keys, 1800)
    pipeline._give_up(item, RuntimeError("x"))                         # yetkazilmadi: qayta yozsa o'tadi
    assert not env.crud.seen_recently(item.undo_keys, 1800)
