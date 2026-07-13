"""sentence-transformers 기반 사전 클러스터링(LLM 호출 전 토큰 절감)."""

from __future__ import annotations

from typing import cast

import numpy as np
from loguru import logger
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from src.dtos import EnrichedMessage, PreCluster

DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def _union_find_groups(similarity: NDArray[np.float32], threshold: float) -> list[list[int]]:
    """대칭 유사도 행렬에서 threshold 이상인 쌍을 union-find로 묶어 그룹 인덱스 리스트 반환."""
    n = similarity.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if float(similarity[i][j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


class PreClusterService:
    """임베딩 기반 사전 클러스터링. cosine 유사도 threshold 이상을 병합."""

    def __init__(
        self,
        threshold: float,
        model: SentenceTransformer | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self._threshold = threshold
        self._model = model if model is not None else SentenceTransformer(model_name)

    def cluster(self, messages: list[EnrichedMessage]) -> list[PreCluster]:
        if not messages:
            return []
        texts = [m.combined_text for m in messages]
        embeddings = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        sim = cast(NDArray[np.float32], embeddings @ embeddings.T)
        groups = _union_find_groups(sim, self._threshold)
        clusters = [self._build_cluster([messages[i] for i in idxs]) for idxs in groups]
        logger.info(f"pre-cluster: {len(messages)}건 → {len(clusters)}개 클러스터")
        return clusters

    @staticmethod
    def _build_cluster(members: list[EnrichedMessage]) -> PreCluster:
        representative = max(members, key=lambda m: len(m.combined_text))
        return PreCluster(representative=representative, members=members)
