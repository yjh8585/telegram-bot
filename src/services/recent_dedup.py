"""실행 간(cross-run) 의미 중복 필터.

최근 window 시간 내 발송한 토픽과 의미가 유사한 새 메시지를 enrichment·요약 전에 제거한다.
임베딩은 pre_cluster와 동일한 SentenceTransformer를 주입받아 재사용한다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np
from loguru import logger
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository

_DROP_LOG_SNIPPET = 40  # 제거 로그에 남길 본문 길이
_NEAR_MISS_TOP_N = 3  # 유지분 중 기억과 가장 가까웠던 상위 N건을 진단 로그로 남김(임계값 튜닝용)
_URL_RE = re.compile(r"https?://\S+")


def _strip_urls(text: str) -> str:
    """URL을 제거해 사람이 쓴 본문만 남긴다.

    링크만 있는 글은 임베딩이 URL 문자열 구조에 지배당해 서로 다른 기사도 유사하게
    나오므로(오탐), 유사도 판단은 실제 본문으로만 한다.
    """
    return _URL_RE.sub(" ", text).strip()


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
        recent_texts = [t for t in map(_strip_urls, self._state.get_recent_topic_texts(since)) if t]
        stripped = [_strip_urls(m.text or "") for m in messages]
        # 링크만 있어 본문이 빈 메시지는 비교에서 제외(무조건 유지).
        cmp_idx = [i for i, t in enumerate(stripped) if t]
        if not recent_texts or not cmp_idx:
            logger.info(
                f"recent-dedup: 비교 생략(기억 {len(recent_texts)}건·대상 {len(cmp_idx)}건) "
                f"→ 전체 {len(messages)}건 유지"
            )
            return messages
        sim = self._similarity([stripped[i] for i in cmp_idx], recent_texts)
        local_drop = _drop_indices(sim, self._threshold)
        drop = {cmp_idx[k] for k in local_drop}
        best_sim = {cmp_idx[k]: float(sim[k].max()) for k in range(len(cmp_idx))}
        return self._log_and_keep(messages, drop, best_sim)

    def _similarity(
        self, msg_texts: list[str], recent_texts: list[str]
    ) -> NDArray[np.float32]:
        """새 메시지 × 최근 텍스트 cosine 유사도 행렬(입력은 URL 제거된 본문)."""
        msg_emb = self._model.encode(
            msg_texts, normalize_embeddings=True, convert_to_numpy=True
        )
        rec_emb = self._model.encode(
            recent_texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return cast(NDArray[np.float32], msg_emb @ rec_emb.T)

    def _log_and_keep(
        self,
        messages: list[RawMessage],
        drop: set[int],
        best_sim: dict[int, float],
    ) -> list[RawMessage]:
        """제거 건과 유지분 최근접(진단)을 로그로 남기고 유지 목록을 반환."""
        kept: list[RawMessage] = []
        for i, m in enumerate(messages):
            if i not in drop:
                kept.append(m)
                continue
            snippet = (m.text or "").replace("\n", " ")[:_DROP_LOG_SNIPPET]
            logger.info(
                f"[recent-dedup] drop ({m.channel_username}) "
                f"sim={best_sim.get(i, 0.0):.3f} | {snippet}"
            )
        self._log_near_misses(messages, drop, best_sim)
        logger.info(
            f"recent-dedup: 총 {len(messages)}건 → 유지 {len(kept)}건(제거 {len(drop)}건)"
        )
        return kept

    def _log_near_misses(
        self,
        messages: list[RawMessage],
        drop: set[int],
        best_sim: dict[int, float],
    ) -> None:
        """유지된 메시지 중 기억과 가장 가까웠던 상위 N건(진단). 임계값·저장방식 튜닝 근거.

        제거는 안 됐지만 반복성이 의심되는 글이 실제 몇 점이었는지 사후 확인용.
        """
        kept_sims = sorted(
            ((best_sim[i], i) for i in best_sim if i not in drop),
            reverse=True,
        )
        for sim, i in kept_sims[:_NEAR_MISS_TOP_N]:
            snippet = (messages[i].text or "").replace("\n", " ")[:_DROP_LOG_SNIPPET]
            logger.info(
                f"[recent-dedup] near ({messages[i].channel_username}) sim={sim:.3f} | {snippet}"
            )
