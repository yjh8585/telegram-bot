"""KST 기준 4개 발송 window 판정."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

WindowLabel = Literal["morning", "late_morning", "afternoon", "evening"]

# 각 슬롯의 KST 발송 시각
SLOT_TIMES: dict[WindowLabel, time] = {
    "morning": time(7, 30),
    "late_morning": time(11, 0),
    "afternoon": time(15, 0),
    "evening": time(18, 0),
}

_ORDER: tuple[WindowLabel, ...] = ("morning", "late_morning", "afternoon", "evening")


class Window(NamedTuple):
    """수집 window. KST 기준 aware datetime."""

    label: WindowLabel
    start: datetime
    end: datetime

    @property
    def start_utc(self) -> datetime:
        return self.start.astimezone(UTC)

    @property
    def end_utc(self) -> datetime:
        return self.end.astimezone(UTC)

    @property
    def header_text(self) -> str:
        """Telegram 메시지 상단에 표시할 사람 친화 헤더."""
        start_str = self.start.strftime("%m/%d %H:%M")
        end_str = self.end.strftime("%m/%d %H:%M")
        return f"{end_str} 기준 · {start_str} ~ {end_str} 요약"


def _slot_datetime(d: date, label: WindowLabel) -> datetime:
    return datetime.combine(d, SLOT_TIMES[label], tzinfo=KST)


def _build(end_date: date, end_label: WindowLabel) -> Window:
    end_dt = _slot_datetime(end_date, end_label)
    idx = _ORDER.index(end_label)
    if idx == 0:
        # 07:30 → 전일 18:00
        start_dt = _slot_datetime(end_date - timedelta(days=1), "evening")
    else:
        start_dt = _slot_datetime(end_date, _ORDER[idx - 1])
    return Window(label=end_label, start=start_dt, end=end_dt)


def current_window(now: datetime | None = None) -> Window:
    """현재(또는 주어진) 시각 기준 '가장 최근 종료된 슬롯' window 반환."""
    now_kst = (now or datetime.now(KST)).astimezone(KST)
    today = now_kst.date()
    for idx in range(len(_ORDER) - 1, -1, -1):
        end_label = _ORDER[idx]
        if now_kst >= _slot_datetime(today, end_label):
            return _build(today, end_label)
    # 모든 슬롯이 미래 → 전일 evening
    return _build(today - timedelta(days=1), "evening")


def window_by_label(label: WindowLabel, now: datetime | None = None) -> Window:
    """명시 label의 window를 반환(수동 실행용)."""
    now_kst = (now or datetime.now(KST)).astimezone(KST)
    return _build(now_kst.date(), label)
