"""봇에게 보낸 최근 메시지의 chat_id를 출력.

사전 조건: 먼저 Telegram 앱에서 내가 그 봇에게 아무 메시지나 1회 보내야 함.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from telegram import Bot

# .env 파일에서 BOT_TOKEN 직접 읽기 (다른 환경변수가 없어도 동작)
def _load_bot_token() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        token = input("BOT_TOKEN을 입력하세요: ").strip()
    return token


async def main() -> None:
    token = _load_bot_token()
    if not token:
        print("BOT_TOKEN이 없습니다. .env 파일에 BOT_TOKEN=<값> 을 추가하거나 직접 입력하세요.")
        return

    bot = Bot(token=token)
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
