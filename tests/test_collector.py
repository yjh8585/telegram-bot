"""CollectorService: last_seen 기반 스킵 + 여러 채널 누적 + commit 로직."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository
from src.services import collector as collector_module
from src.services.collector import CollectorService
from src.window import Window

KST = ZoneInfo("Asia/Seoul")


def _raw(channel: str, mid: int) -> RawMessage:
    return RawMessage(
        channel_username=channel,
        message_id=mid,
        posted_at=datetime(2026, 4, 24, tzinfo=UTC),
    )


def _window() -> Window:
    return Window(
        label="evening",
        start=datetime(2026, 4, 24, 15, 0, tzinfo=KST),
        end=datetime(2026, 4, 24, 18, 0, tzinfo=KST),
    )


@pytest.mark.asyncio
async def test_collect_multiple_channels_accumulates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collector_module, "CHANNELS", ("ch1", "ch2"))
    state = StateRepository(tmp_path / "s.db")
    tg = AsyncMock()
    tg.fetch_window.side_effect = [
        [_raw("ch1", 1), _raw("ch1", 2)],
        [_raw("ch2", 100)],
    ]
    svc = CollectorService(tg, state)
    out = await svc.collect(_window())
    assert [m.message_id for m in out] == [1, 2, 100]
    state.close()


@pytest.mark.asyncio
async def test_collect_skips_already_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collector_module, "CHANNELS", ("ch",))
    state = StateRepository(tmp_path / "s.db")
    state.set_last_seen("ch", 10)
    tg = AsyncMock()
    tg.fetch_window.return_value = [_raw("ch", 5), _raw("ch", 11), _raw("ch", 12)]
    svc = CollectorService(tg, state)
    out = await svc.collect(_window())
    assert [m.message_id for m in out] == [11, 12]
    state.close()


def test_commit_last_seen_uses_max_per_channel(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "s.db")
    svc = CollectorService(AsyncMock(), state)
    svc.commit_last_seen(
        [
            _raw("ch1", 5),
            _raw("ch1", 7),
            _raw("ch1", 3),
            _raw("ch2", 2),
        ]
    )
    assert state.get_last_seen("ch1") == 7
    assert state.get_last_seen("ch2") == 2
    state.close()


def test_commit_last_seen_empty_list_noop(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "s.db")
    svc = CollectorService(AsyncMock(), state)
    svc.commit_last_seen([])
    assert state.get_last_seen("ch") is None
    state.close()
