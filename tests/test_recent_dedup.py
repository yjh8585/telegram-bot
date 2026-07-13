"""RecentDedupService 및 _drop_indices 단위 테스트(임베딩 모델 미로드)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository
from src.services.recent_dedup import RecentDedupService, _drop_indices


def test_drop_indices_basic() -> None:
    sim = np.array([[0.9, 0.1], [0.2, 0.3]], dtype=np.float32)
    assert _drop_indices(sim, 0.85) == {0}


def test_drop_indices_empty() -> None:
    assert _drop_indices(np.empty((0, 0), dtype=np.float32), 0.85) == set()
    assert _drop_indices(np.empty((3, 0), dtype=np.float32), 0.85) == set()


class _FakeModel:
    """텍스트→고정 벡터 매핑을 정규화해 반환하는 가짜 임베더."""

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def encode(
        self,
        texts: list[str],
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> np.ndarray:
        vecs = np.array([self._mapping[t] for t in texts], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms


def _msg(text: str, mid: int) -> RawMessage:
    return RawMessage(
        channel_username="ch",
        message_id=mid,
        posted_at=datetime(2026, 7, 13, tzinfo=UTC),
        text=text,
    )


def test_filter_new_drops_duplicate(tmp_path: Path) -> None:
    model = _FakeModel(
        {"삼성 실적": [1.0, 0.0], "삼성전자 실적 발표": [1.0, 0.0], "환율 뉴스": [0.0, 1.0]}
    )
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, tzinfo=UTC)
        repo.add_recent_topics(["삼성 실적"], t0)
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new(
            [_msg("삼성전자 실적 발표", 1), _msg("환율 뉴스", 2)],
            now=t0 + timedelta(hours=1),
        )
        assert [m.text for m in kept] == ["환율 뉴스"]
    finally:
        repo.close()


def test_filter_new_empty_store_keeps_all(tmp_path: Path) -> None:
    model = _FakeModel({"a": [1.0, 0.0]})
    repo = StateRepository(tmp_path / "s.db")
    try:
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new([_msg("a", 1)], now=datetime(2026, 7, 13, tzinfo=UTC))
        assert len(kept) == 1
    finally:
        repo.close()


def test_filter_new_outside_window_keeps(tmp_path: Path) -> None:
    """기억이 창(24h) 밖이면 비교 대상에서 빠져 메시지가 유지된다."""
    model = _FakeModel({"삼성 실적": [1.0, 0.0], "삼성전자 실적 발표": [1.0, 0.0]})
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, tzinfo=UTC)
        repo.add_recent_topics(["삼성 실적"], t0)
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new(
            [_msg("삼성전자 실적 발표", 1)], now=t0 + timedelta(hours=25)
        )
        assert len(kept) == 1
    finally:
        repo.close()
