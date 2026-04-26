"""Claude Haiku 4.5 1회 호출로 PreCluster 리스트 → ClusteredTopic 리스트로 통합 요약."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from json_repair import repair_json

from anthropic import Anthropic
from loguru import logger

from src.config import PROJECT_ROOT
from src.dtos import ClusteredTopic, Importance, PreCluster, SourceRef
from src.services.vision import NO_INFO_MARKER

_PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "cluster_merge.md"
_MAX_TOKENS = 8000
_REP_TEXT_LIMIT = 1500
_VALID_IMPORTANCE: tuple[Importance, ...] = ("high", "medium", "low")


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_text_block(msg: Any) -> str:
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _build_user_payload(clusters: list[PreCluster]) -> str:
    items = [
        {
            "cluster_id": i,
            "representative_text": c.representative.combined_text[:_REP_TEXT_LIMIT],
            "tickers": [t.code for t in c.representative.tickers],
            "sources": [
                {"channel": m.raw.channel_username, "message_id": m.raw.message_id}
                for m in c.members
            ],
        }
        for i, c in enumerate(clusters)
    ]
    header = "다음 클러스터들을 시스템 프롬프트에 따라 JSON 배열로 요약하세요.\n\n입력:\n"
    return header + json.dumps(items, ensure_ascii=False, indent=2)


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


def _collect_images(cluster: PreCluster) -> list[bytes]:
    """클러스터 내 의미 있는 이미지 바이트 목록을 반환."""
    images: list[bytes] = []
    for member in cluster.members:
        if (
            member.raw.photo_bytes is not None
            and member.image_description is not None
            and NO_INFO_MARKER not in member.image_description
        ):
            images.append(member.raw.photo_bytes)
    return images


def _build_topic(item: Any, clusters: list[PreCluster]) -> ClusteredTopic | None:
    if not isinstance(item, dict):
        return None
    cid = item.get("cluster_id")
    if not isinstance(cid, int) or cid < 0 or cid >= len(clusters):
        return None
    raw_importance = item.get("importance") or "medium"
    importance: Importance = (
        cast(Importance, raw_importance) if raw_importance in _VALID_IMPORTANCE else "medium"
    )
    sources: list[SourceRef] = clusters[cid].all_sources
    tickers = [str(t) for t in (item.get("tickers") or []) if isinstance(t, str)]
    images = _collect_images(clusters[cid])
    return ClusteredTopic(
        title=str(item.get("title") or "").strip(),
        summary=str(item.get("summary") or "").strip(),
        importance=importance,
        sources=sources,
        tickers=tickers,
        images=images,
    )


class DedupeSummarizerService:
    """Claude에 1회 호출로 전체 클러스터를 통합 요약."""

    def __init__(self, client: Anthropic, model: str) -> None:
        self._client = client
        self._model = model
        self._system_prompt = _load_system_prompt()

    def summarize(self, clusters: list[PreCluster]) -> list[ClusteredTopic]:
        if not clusters:
            return []
        user_payload = _build_user_payload(clusters)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": self._system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_payload}],
            )
        except Exception as e:
            logger.error(f"Claude summarize 실패: {e}")
            return []
        raw_text = _extract_text_block(response)
        return _parse_topics(raw_text, clusters)
