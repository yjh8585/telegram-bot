"""여러 채널에서 window 내 메시지를 수집하는 서비스."""

from __future__ import annotations

from datetime import timedelta

from loguru import logger

from src.config import CHANNELS
from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository
from src.repositories.telethon_repo import TelethonRepository
from src.window import Window

# last_seen이 있을 때 window.start 기준으로 since를 거슬러 올리는 안전 마진.
# morning window 최대 크기(~13.5h) 이상을 커버하면서 1일치 수집을 방지한다.
_SAFETY_LOOKBACK = timedelta(hours=16)


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
        last_seen = self._state.get_last_seen(channel) or 0
        # window 경계를 엄수 — 지연 실행 시 window 밖 메시지는 다음 실행에서 수집.
        # 이전 방식(max(end, now_utc))은 수집 범위를 현재 시각까지 넓혀 실행 시간을 늘렸음.
        effective_until = window.end_utc
        # last_seen이 있으면 window.start 기준 lookback으로 직전 누락 복구.
        # 중복은 min_id가 방지한다.
        effective_since = (
            window.start_utc - _SAFETY_LOOKBACK if last_seen > 0 else window.start_utc
        )
        msgs = await self._tg.fetch_window(
            channel, effective_since, effective_until, min_id=last_seen
        )
        # 안전망: 모킹/엣지케이스 대비 ID 필터 한 번 더 적용
        if last_seen > 0:
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
