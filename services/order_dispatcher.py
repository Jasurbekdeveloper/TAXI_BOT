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
    """Yagona format (services/card.py) — oddiy yo'lovchi e'lonlari bilan bir xil."""
    from services.card import render_card
    return render_card(frm=o.frm, to=o.to, text_phone=o.phone, profile_phone=o.profile_phone, name=o.name,
                       username=o.username, text=o.text, user_id=o.user_id,
                       source_title=o.source_title or "Donor guruh", source_url=o.source_url, order_no=order_no)


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
    if not o.username and (o.user_id or o.phone):   # username yo'q: «💬 Yozish» bosilsa bot mijozni qidiradi
        try:
            from services import order_contact
            order_no = order_contact.save(o.user_id, None, order_contact.active_owner(), None,
                                          src_chat=o.chat_id, src_msg=o.msg_id, snippet=(o.text or "")[:200], phone=o.phone,
                                          profile_phone=o.profile_phone)
        except Exception as e:
            log.warning("#Order (donor) saqlanmadi: %s", e)
    await queue.put(Outgoing(render(o, order_no), key="donor:" + (keys[0] if keys else str(o.msg_id)),
                             order_no=order_no,
                             contact_url=f"https://t.me/{o.username}" if o.username else None,
                             chat_id=target, style="donor", undo_keys=keys,
                             source_url=o.source_url,
                             # donorga guruh qattiq biriktirilmagan bo'lsa — yo'nalish bo'yicha qayta aniqlanadi
                             route=None if donor is not None and donor["target_chat_id"] else (o.frm, o.to)))
    return "sent"
