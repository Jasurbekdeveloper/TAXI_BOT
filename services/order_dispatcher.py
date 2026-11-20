"""Donor parserdan kelgan mijozni yopiq haydovchilar guruhiga uzatish.

Xabarda mijoz lichkasiga ikki yo'l bor: matn ichida yashirin havola va pastda inline tugma
(«👤 Клиент личкаси» + «✅ Buyurtmani oldim»). Havola: @username bo'lsa https://t.me/<username>,
bo'lmasa tg://user?id=<id>. Yuborish pipeline navbati orqali (Telegram limitlari, qayta urinish, «Oldim»).
Mijoz yashirgan profilga tugma Telegram tomonidan rad etilsa, xabar tugmasiz qayta yuboriladi (pipeline._deliver).
Dublikat: bir xil User ID / username / telefon DONOR_DEDUP_MINUTES ichida qayta uzatilmaydi (SQLite).
"""
import html
import logging

import config
import routes
from database import crud
from nlp import tel
from services.donor_parser import DonorOrder

log = logging.getLogger(__name__)


def render(o: DonorOrder, order_no: int | None = None) -> str:
    e = html.escape
    lines = ["🚖 <b>Yangi mijoz aniqlandi!</b>",
             f"🆔 <b>User ID:</b> <code>{o.user_id}</code>" if o.user_id else "🆔 <b>User ID:</b> —"]
    if o.frm or o.to:
        lines.append(f"📍 {e(o.frm or '?')} → {e(o.to or '?')}")
    lines += ["", f"📝 <b>Xabar:</b> {e(o.text)}",
              f"📞 <b>Tel:</b> {e(tel(o.phone)) if o.phone else 'koʻrsatilmagan'}"]   # bo'shliqsiz — bosib qo'ng'iroq
    if o.link:
        link = e(o.link, quote=True)
        lines += ["", f'👤 <a href="{link}">Клиент личкаси</a>', f'✍️ <a href="{link}">Клиентга ёзиш</a>']
        if o.username:
            lines.append(f"@{e(o.username)}")
        elif not o.phone:
            # username/telefon yo'q: tg://user havolasi begona uchun ochilmasligi mumkin — ID bilan ogohlantiramiz
            lines.append("ℹ️ <i>Havola ochilmasa — User ID orqali toping</i>")
    # Manba uchun «🔗 Xabarga o'tish» tugmasi (source_url) yetarli — xunuk chat_id qatori qo'shilmaydi
    from pipeline import route_hashtag
    tag = route_hashtag(o.frm, o.to)
    if tag:
        lines.append(tag)
    if order_no:                                # reply qilsa ham userbot mijozga yozadi
        lines.append(f"#Order_{order_no}")
    return "\n".join(lines)


def target_for(o: DonorOrder, donor) -> int | None:
    """Donorga biriktirilgan yopiq guruh; bo'lmasa yo'nalish bo'yicha (Smart Routing). None = yuborilmaydi."""
    if donor is not None and donor["target_chat_id"]:
        return donor["target_chat_id"]
    if not routes.allowed(o.frm, o.to):
        return None
    return routes.target_chat(o.frm, o.to)


async def dispatch(o: DonorOrder, donor=None) -> str:
    from pipeline import Outgoing, queue, stats
    keys = o.dedup_keys()
    if crud.seen_recently(keys, config.DONOR_DEDUP_MINUTES * 60):
        stats["dup"] += 1
        return "dup"
    target = target_for(o, donor)
    if not target:
        return "skip"
    crud.mark_dispatched(keys)
    if donor is not None:
        crud.donor_forwarded(o.chat_id)
    stats["donor"] += 1
    log.info("[donor] %s → %s | uid=%s un=%s tel=%s", o.chat_id, target, o.user_id, o.username, o.phone)
    order_no = None
    if o.user_id and not o.username:            # username yo'q: havola rad etilsa — #Order orqali yoziladi
        try:
            from services import order_contact
            order_no = order_contact.save(o.user_id, None, order_contact.active_owner(), None,
                                          src_chat=o.chat_id, src_msg=o.msg_id, snippet=(o.text or "")[:200])
        except Exception as e:
            log.warning("#Order (donor) saqlanmadi: %s", e)
    await queue.put(Outgoing(render(o, order_no), key="donor:" + (keys[0] if keys else str(o.msg_id)),
                             order_no=order_no,
                             contact_url=o.link, chat_id=target, style="donor", undo_keys=keys,
                             source_url=o.source_url,
                             # donorga guruh qattiq biriktirilmagan bo'lsa — yo'nalish bo'yicha qayta aniqlanadi
                             route=None if donor is not None and donor["target_chat_id"] else (o.frm, o.to)))
    return "sent"
