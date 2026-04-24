"""window 판정 로직 단위 테스트."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.window import current_window, window_by_label

KST = ZoneInfo("Asia/Seoul")


def test_evening_window() -> None:
    now = datetime(2026, 4, 24, 18, 5, tzinfo=KST)
    w = current_window(now)
    assert w.label == "evening"
    assert w.start == datetime(2026, 4, 24, 15, 0, tzinfo=KST)
    assert w.end == datetime(2026, 4, 24, 18, 0, tzinfo=KST)


def test_morning_window_spans_previous_day() -> None:
    now = datetime(2026, 4, 24, 7, 35, tzinfo=KST)
    w = current_window(now)
    assert w.label == "morning"
    assert w.start == datetime(2026, 4, 23, 18, 0, tzinfo=KST)
    assert w.end == datetime(2026, 4, 24, 7, 30, tzinfo=KST)


def test_before_morning_uses_previous_evening() -> None:
    now = datetime(2026, 4, 24, 5, 0, tzinfo=KST)
    w = current_window(now)
    assert w.label == "evening"
    assert w.start == datetime(2026, 4, 23, 15, 0, tzinfo=KST)
    assert w.end == datetime(2026, 4, 23, 18, 0, tzinfo=KST)


def test_window_by_label_afternoon() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=KST)
    w = window_by_label("afternoon", now)
    assert w.label == "afternoon"
    assert w.start == datetime(2026, 4, 24, 11, 0, tzinfo=KST)
    assert w.end == datetime(2026, 4, 24, 15, 0, tzinfo=KST)


def test_late_morning_window() -> None:
    now = datetime(2026, 4, 24, 11, 5, tzinfo=KST)
    w = current_window(now)
    assert w.label == "late_morning"
    assert w.start == datetime(2026, 4, 24, 7, 30, tzinfo=KST)
    assert w.end == datetime(2026, 4, 24, 11, 0, tzinfo=KST)


def test_utc_conversion() -> None:
    now = datetime(2026, 4, 24, 18, 5, tzinfo=KST)
    w = current_window(now)
    # KST 15:00 → UTC 06:00
    assert w.start_utc.hour == 6
    assert w.end_utc.hour == 9
