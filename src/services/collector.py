"""여러 채널에서 window 내 메시지를 수집하는 서비스."""

from __future__ import annotations

from loguru import logger

from src.config import CHANNELS
from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository
from src.repositories.telethon_repo import TelethonRepository
from src.window import Window


class CollectorService:
    """TelethonRepository + StateRepository 조합으로 window 수집을 담당."""

    def __init__(self, tg: TelethonRepository, state: StateRepository) -> None:
        self._tg = tg
        self._state = state

    async def collect(self, window: Window) -> list[RawMessage]:
        """모든 대상 채널에서 window 내 메시지 수집 후 하나의 리스트로 반환."""
        all_msgs: list[RawMessage] = []
        for channel in CHANNELS:
            msgs = await self._collect_one(channel, window)
            logger.info(f"[{channel}] {len(msgs)}개 수집")
            all_msgs.extend(msgs)
        return all_msgs

    async def _collect_one(self, channel: str, window: Window) -> list[RawMessage]:
        last_seen = self._state.get_last_seen(channel)
        msgs = await self._tg.fetch_window(channel, window.start_utc, window.end_utc)
        if last_seen is not None:
            msgs = [m for m in msgs if m.message_id > last_seen]
        return msgs

    def commit_last_seen(self, messages: list[RawMessage]) -> None:
        """채널별 최대 message_id를 last_seen으로 기록(최종 발송 후 호출)."""
        by_channel: dict[str, int] = {}
        for m in messages:
            by_channel[m.channel_username] = max(
                by_channel.get(m.channel_username, 0), m.message_id
            )
        for channel, mid in by_channel.items():
            self._state.set_last_seen(channel, mid)
