"""실행 간(cross-run) 의미 중복 필터.

최근 window 시간 내 발송한 토픽과 의미가 유사한 새 메시지를 enrichment·요약 전에 제거한다.
임베딩은 pre_cluster와 동일한 SentenceTransformer를 주입받아 재사용한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np
from loguru import logger
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository

_DROP_LOG_SNIPPET = 40  # 제거 로그에 남길 본문 길이


def _drop_indices(sim: NDArray[np.float32], threshold: float) -> set[int]:
    """sim[i][j]=메시지 i vs 최근 텍스트 j 유사도. 행별 최대가 threshold 이상인 메시지 인덱스."""
    if sim.size == 0:
        return set()
    max_per_row = sim.max(axis=1)
    return {int(i) for i in np.nonzero(max_per_row >= threshold)[0]}


class RecentDedupService:
    """최근 발송 토픽과 유사한 새 메시지를 제거하는 서비스."""

    def __init__(
        self,
        threshold: float,
        window_hours: int,
        state: StateRepository,
        model: SentenceTransformer,
    ) -> None:
        self._threshold = threshold
        self._window = timedelta(hours=window_hours)
        self._state = state
        self._model = model

    def filter_new(
        self, messages: list[RawMessage], now: datetime | None = None
    ) -> list[RawMessage]:
        """최근 발송 토픽과 유사한 메시지를 제거하고 나머지를 반환."""
        current = now or datetime.now(UTC)
        since = current - self._window
        recent_texts = self._state.get_recent_topic_texts(since)
        if not messages or not recent_texts:
            return messages
        sim = self._similarity(messages, recent_texts)
        drop = _drop_indices(sim, self._threshold)
        return self._log_and_keep(messages, sim, drop)

    def _similarity(
        self, messages: list[RawMessage], recent_texts: list[str]
    ) -> NDArray[np.float32]:
        """새 메시지 × 최근 텍스트 cosine 유사도 행렬."""
        msg_emb = self._model.encode(
            [m.text or "" for m in messages],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        rec_emb = self._model.encode(
            recent_texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return cast(NDArray[np.float32], msg_emb @ rec_emb.T)

    def _log_and_keep(
        self,
        messages: list[RawMessage],
        sim: NDArray[np.float32],
        drop: set[int],
    ) -> list[RawMessage]:
        """제거 건을 로그로 남기고 유지 목록을 반환."""
        kept: list[RawMessage] = []
        for i, m in enumerate(messages):
            if i not in drop:
                kept.append(m)
                continue
            snippet = (m.text or "").replace("\n", " ")[:_DROP_LOG_SNIPPET]
            best = float(sim[i].max())
            logger.info(
                f"[recent-dedup] drop ({m.channel_username}) sim={best:.3f} | {snippet}"
            )
        logger.info(
            f"recent-dedup: 총 {len(messages)}건 → 유지 {len(kept)}건(제거 {len(drop)}건)"
        )
        return kept
