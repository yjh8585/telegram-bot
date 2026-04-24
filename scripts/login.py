"""Telethon 최초 로그인 후 StringSession을 출력.

실행 순서:
  1) `python scripts/login.py`
  2) api_id, api_hash 입력 (https://my.telegram.org)
  3) 전화번호, Telegram 앱으로 온 코드, (있으면) 2단계 비밀번호 입력
  4) 마지막에 출력되는 SESSION_STRING을 .env의 TG_SESSION_STRING과
     GitHub Secrets의 TG_SESSION_STRING에 등록.
"""
from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()

    client = TelegramClient(StringSession(), api_id, api_hash)
    async with client:
        # client.start()는 __aenter__ 내에서 이미 수행됨 (Telethon context manager 규약)
        session_str = client.session.save()

    print()
    print("=" * 60)
    print("아래 값을 .env의 TG_SESSION_STRING 과 GitHub Secrets에 등록:")
    print("=" * 60)
    print(session_str)


if __name__ == "__main__":
    asyncio.run(main())
