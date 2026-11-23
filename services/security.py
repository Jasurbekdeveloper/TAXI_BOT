"""Ishga tushishda xavfsizlik tekshiruvi: maxfiy fayllar faqat egasiga o'qiladigan bo'ladi, xavfli holatlar logga.

Maxfiy fayllar: .env (token, API kalitlari), *.session (userbot — ochiq kalit!), fernet.key (haydovchi
sessiyalari shifri), taxi.db (shifrlangan sessiyalar, foydalanuvchilar), order_contacts.db (mijoz raqamlari).
"""
import logging
import os
import stat

import config

log = logging.getLogger(__name__)

SECRET_GLOBS = (".env", "*.session", "*.session-journal", "fernet.key", "*.db", "*.db-*")


def _secret_files():
    seen = set()
    for pattern in SECRET_GLOBS:
        for p in config.BASE_DIR.glob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield p


def harden() -> list[str]:
    """Ruxsatlarni 600 qiladi (Linux/macOS). Ogohlantirishlar ro'yxatini qaytaradi (ular logga ham yoziladi)."""
    warns = []
    if os.name == "posix":
        for p in _secret_files():
            mode = stat.S_IMODE(p.stat().st_mode)
            if mode & 0o077:
                try:
                    os.chmod(p, 0o600)
                    log.info("[security] %s ruxsati %o -> 600", p.name, mode)
                except OSError as e:
                    warns.append(f"{p.name} ruxsatini o'zgartirib bo'lmadi: {e}")
    if not config.SESSION_SECRET and config.FERNET_KEY_FILE.exists():
        warns.append("Haydovchi sessiyalari kaliti fayl ichida (fernet.key) — u bazaning yonida turibdi. "
                     "Kalitni .env dagi SESSION_SECRET ga ko'chiring va faylni o'chiring.")
    elif config.SESSION_SECRET and config.FERNET_KEY_FILE.exists():
        warns.append("SESSION_SECRET berilgan, lekin fernet.key fayli hali serverda turibdi — "
                     "sessiyalar ochilayotganini tekshirib, faylni o'chiring (zaxirasini xavfsiz joyda saqlang).")
    for p in config.BASE_DIR.glob("*"):
        if p.is_file() and (p.suffix in (".key", ".pem") or p.name.startswith(("id_rsa", "id_ed25519", "ssh-key"))) \
                and p.name != config.FERNET_KEY_FILE.name:
            warns.append(f"Loyiha papkasida SSH/maxfiy kalit fayli bor: {p.name} — uni ~/.ssh ga ko'chiring.")
    for w in warns:
        log.warning("[security] %s", w)
    return warns
