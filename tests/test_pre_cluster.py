"""pre_cluster union-find 병합 로직 단위 테스트(임베딩 로드 없이)."""
from __future__ import annotations

import numpy as np

from src.services.pre_cluster import _union_find_groups


def _as_groups(lists: list[list[int]]) -> list[frozenset[int]]:
    return sorted([frozenset(g) for g in lists], key=lambda s: min(s))


def test_no_merge_below_threshold() -> None:
    sim = np.array([[1.0, 0.5, 0.3], [0.5, 1.0, 0.2], [0.3, 0.2, 1.0]], dtype=np.float32)
    groups = _as_groups(_union_find_groups(sim, threshold=0.82))
    assert groups == [frozenset({0}), frozenset({1}), frozenset({2})]


def test_two_similar_merge() -> None:
    sim = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]], dtype=np.float32)
    groups = _as_groups(_union_find_groups(sim, threshold=0.82))
    assert groups == [frozenset({0, 1}), frozenset({2})]


def test_chained_transitivity() -> None:
    # A-B 유사, B-C 유사, A-C 직접은 낮아도 체이닝으로 하나로 묶여야 함
    sim = np.array(
        [
            [1.0, 0.85, 0.5],
            [0.85, 1.0, 0.85],
            [0.5, 0.85, 1.0],
        ],
        dtype=np.float32,
    )
    groups = _as_groups(_union_find_groups(sim, threshold=0.82))
    assert groups == [frozenset({0, 1, 2})]


def test_empty_matrix() -> None:
    sim = np.empty((0, 0), dtype=np.float32)
    assert _union_find_groups(sim, threshold=0.82) == []
