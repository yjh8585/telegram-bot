"""Telegram Bot API로 DM 전송."""

from __future__ import annotations

from loguru import logger
from telegram import Bot
from telegram.constants import ParseMode


class NotifierService:
    """Bot 토큰으로 개인 chat_id에 MarkdownV2 DM을 전송."""

    def __init__(self, bot_token: str, chat_id: int) -> None:
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id

    async def send_messages(self, messages: list[str]) -> None:
        if not messages:
            return
        async with self._bot:
            for msg in messages:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_web_page_preview=True,
                )

    async def send_error(self, error_text: str) -> None:
        """오케스트레이션에서 잡힌 최종 예외를 봇 자신이 DM으로 받음."""
        preview = error_text[:3500]
        try:
            async with self._bot:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=f"⚠️ 봇 오류\n{preview}",
                    disable_web_page_preview=True,
                )
        except Exception as e:  # 실패하면 stdout 로그로 남기고 끝
            logger.error(f"에러 DM 발송 실패: {e}")
