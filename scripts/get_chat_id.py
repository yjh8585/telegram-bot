"""봇에게 보낸 최근 메시지의 chat_id를 출력.

사전 조건: 먼저 Telegram 앱에서 내가 그 봇에게 아무 메시지나 1회 보내야 함.
"""
from __future__ import annotations

import asyncio

from telegram import Bot

from src.config import get_settings
from src.logger import setup_logger


async def main() -> None:
    setup_logger()
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    async with bot:
        updates = await bot.get_updates(timeout=0)

    if not updates:
        print("수신된 메시지가 없습니다.")
        print("→ 먼저 Telegram 앱에서 그 봇에게 임의 메시지를 1회 보내주세요.")
        return

    for u in updates:
        chat = getattr(u, "effective_chat", None)
        user = getattr(u, "effective_user", None)
        if chat is not None:
            username = user.username if user else "unknown"
            print(f"chat_id={chat.id}  (from: @{username})")


if __name__ == "__main__":
    asyncio.run(main())
