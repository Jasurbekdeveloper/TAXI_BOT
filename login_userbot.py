"""Userbot akkauntga BIR MARTALIK kirish. Terminalда ishga tushiring:

    .venv\\Scripts\\python login_userbot.py

Telefon -> Telegram ilovasидан kelган kod -> (2FA bo'lsa parol).
Kirgach, <SESSION_NAME>.session saqlanadi va main.py qayta login so'ramaydi.
Oxirida akkaunt a'zo bo'lgan guruhlar ro'yxatини ko'rsatади — agregatorда shular tanlanadi.
"""
import asyncio

import config

if config.USE_SYSTEM_CA:
    import truststore
    truststore.inject_into_ssl()


async def main():
    from telethon import TelegramClient

    if not (config.API_ID and config.API_HASH):
        print("XATO: .env da API_ID va API_HASH bo'lishi kerak (my.telegram.org dan).")
        return

    client = TelegramClient(str(config.BASE_DIR / config.SESSION_NAME), config.API_ID, config.API_HASH)
    print("Ulanmoqda... Telefon raqам so'ralganда userbot akkaunt raqамини kiriting (+998...).")
    print("Kod SMS emas, Telegram ilovasидаги 'Telegram' chatига keladi.\n")
    try:
        await client.start()
    except Exception as e:
        print(f"\nXATO: {e}")
        print("Agar 'api_id/api_hash invalid' bo'lsa — my.telegram.org dan haqiqiy API_ID/API_HASH oling.")
        return

    me = await client.get_me()
    uname = f"@{me.username}" if me.username else "(username yo'q)"
    print(f"\n✅ Kirildi: {me.first_name} {uname}. Sessiya saqlandi: {config.SESSION_NAME}.session")

    print("\n--- Akkaunt a'zo bo'lgan GURUHLAR (agregatorда shular tanlanadi) ---")
    n = 0
    async for d in client.iter_dialogs():
        if getattr(d, "is_group", False):
            n += 1
            print(f"  {d.id}   {d.title}")
    if n == 0:
        print("  (Akkaunt hali hеch qanday guruhга a'zo emas — avval taksi guruhlarига qo'shiling.)")
    print(f"\nJami: {n} ta guruh. Endi `python main.py` ni ishga tushirishingiz mumkin.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
