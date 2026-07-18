"""Claude Haiku 4.5 1회 호출로 PreCluster 리스트 → ClusteredTopic 리스트로 통합 요약."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from anthropic import Anthropic
from json_repair import repair_json
from loguru import logger

from src.config import PROJECT_ROOT
from src.dtos import ClusteredTopic, Importance, PreCluster, SourceRef
from src.logger import log_api_usage

_PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "cluster_merge.md"
_MAX_TOKENS = 8192  # Haiku 4.5 최대 출력(고정)
# 출력 8192 토큰 잘림 회피용 배치 크기. 토픽당 ~200토큰 가정 → 25×200=5000으로 여유 마진.
_MAX_CLUSTERS_PER_CALL = 25
_VALID_IMPORTANCE: tuple[Importance, ...] = ("high", "medium", "low")


class SummarizeError(RuntimeError):
    """summarize API 호출이 모두 실패해 토픽을 못 만들었을 때 발생.

    빈 리스트로 삼키면 상위에서 'JSON 파싱 확인 필요'라는 오해 소지 진단이 나가므로,
    크레딧 소진·인증 오류·레이트리밋 등 진짜 원인을 그대로 담아 전파한다.
    """


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_text_block(msg: Any) -> str:
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _merge_tickers(cluster: PreCluster) -> list[str]:
    """클러스터 전체 멤버에서 중복 없이 티커 코드 수집."""
    seen: set[str] = set()
    out: list[str] = []
    for m in cluster.members:
        for t in m.tickers:
            if t.code not in seen:
                seen.add(t.code)
                out.append(t.code)
    return out


def _build_user_payload(clusters: list[PreCluster], rep_text_limit: int) -> str:
    items = [
        {
            "cluster_id": i,
            "representative_text": c.representative.combined_text[:rep_text_limit],
            "tickers": _merge_tickers(c),
            "sources": [
                {"channel": m.raw.channel_username, "message_id": m.raw.message_id}
                for m in c.members
            ],
        }
        for i, c in enumerate(clusters)
    ]
    header = "다음 클러스터들을 시스템 프롬프트에 따라 JSON 배열로 요약하세요.\n\n입력:\n"
    return header + json.dumps(items, ensure_ascii=False, indent=2)


def _cap_clusters(clusters: list[PreCluster], max_topics: int) -> list[PreCluster]:
    """max_topics>0이면 멤버수(신호 강도) 상위 N개만 유지(원래 순서 보존)."""
    if max_topics <= 0 or len(clusters) <= max_topics:
        return clusters
    ranked = sorted(range(len(clusters)), key=lambda i: len(clusters[i].members), reverse=True)
    keep = set(ranked[:max_topics])
    logger.info(
        f"summarize: 클러스터 {len(clusters)}개 → 상위 {max_topics}개 유지"
        f"(제거 {len(clusters) - max_topics}개, 멤버수 기준)"
    )
    return [c for i, c in enumerate(clusters) if i in keep]


def _strip_code_fences(text: str) -> str:
    """마크다운 코드블록(```json ... ```) 제거."""
    return re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", text).strip()


def _parse_topics(raw: str, clusters: list[PreCluster]) -> list[ClusteredTopic]:
    raw = _strip_code_fences(raw)
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        logger.error("summarize 응답에 JSON 배열이 없음")
        return []
    candidate = raw[start : end + 1]
    try:
        arr = json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.warning(f"표준 JSON 파싱 실패, json-repair 시도: {e}")
        try:
            arr = json.loads(repair_json(candidate))
        except Exception as e2:
            logger.error(f"json-repair 후에도 파싱 실패: {e2}")
            return []
    if not isinstance(arr, list):
        return []
    return [topic for topic in (_build_topic(item, clusters) for item in arr) if topic is not None]


def _build_topic(item: Any, clusters: list[PreCluster]) -> ClusteredTopic | None:
    if not isinstance(item, dict):
        return None
    cid = item.get("cluster_id")
    if not isinstance(cid, int) or cid < 0 or cid >= len(clusters):
        return None
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    # title/summary 둘 중 하나라도 비면 무의미 토픽으로 간주해 제외.
    if not title or not summary:
        return None
    raw_importance = item.get("importance") or "medium"
    importance: Importance = (
        cast(Importance, raw_importance) if raw_importance in _VALID_IMPORTANCE else "medium"
    )
    sources: list[SourceRef] = clusters[cid].all_sources
    tickers = [str(t) for t in (item.get("tickers") or []) if isinstance(t, str)]
    return ClusteredTopic(
        title=title,
        summary=summary,
        importance=importance,
        sources=sources,
        tickers=tickers,
    )


class DedupeSummarizerService:
    """Claude에 1회 호출로 전체 클러스터를 통합 요약."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        rep_text_limit: int = 1600,
        max_topics: int = 0,
    ) -> None:
        self._client = client
        self._model = model
        self._rep_text_limit = rep_text_limit
        self._max_topics = max_topics
        self._system_prompt = _load_system_prompt()

    def summarize(self, clusters: list[PreCluster]) -> list[ClusteredTopic]:
        """클러스터를 배치로 나눠 요약(출력 8192 토큰 잘림 방지). 배치별 실패는 격리.

        일부 배치만 API 에러면 나머지 결과를 유지(graceful degrade)한다. 단, 모든 배치가
        API 에러로 토픽 0건이면 진짜 원인을 담아 SummarizeError를 올린다(파싱 0건과 구분).
        """
        if not clusters:
            return []
        clusters = _cap_clusters(clusters, self._max_topics)
        topics: list[ClusteredTopic] = []
        last_api_error: Exception | None = None
        for start in range(0, len(clusters), _MAX_CLUSTERS_PER_CALL):
            batch = clusters[start : start + _MAX_CLUSTERS_PER_CALL]
            try:
                topics.extend(self._summarize_batch(batch))
            except Exception as e:
                logger.error(f"Claude summarize 실패(배치 {len(batch)}건): {e}")
                last_api_error = e
        if not topics and last_api_error is not None:
            raise SummarizeError(
                f"summarize API 호출 실패로 토픽 0건 — {last_api_error}"
            ) from last_api_error
        return topics

    def _summarize_batch(self, clusters: list[PreCluster]) -> list[ClusteredTopic]:
        """단일 배치를 1회 호출로 요약. cluster_id는 배치 내 0부터라 출처 매핑이 그대로 맞는다.

        API 호출 예외는 여기서 삼키지 않고 호출부(summarize)로 전파해 원인을 보존한다.
        """
        user_payload = _build_user_payload(clusters, self._rep_text_limit)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        log_api_usage("summarize", response)
        raw_text = _extract_text_block(response)
        return _parse_topics(raw_text, clusters)
