"""DedupeSummarizerService: Claude 응답 파싱·빈 입력·잘못된 JSON 처리."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.dtos import EnrichedMessage, PreCluster, RawMessage
from src.services.dedupe_summarizer import DedupeSummarizerService


def _enriched(channel: str, mid: int, text: str) -> EnrichedMessage:
    return EnrichedMessage(
        raw=RawMessage(
            channel_username=channel,
            message_id=mid,
            posted_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            text=text,
        )
    )


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_summarize_parses_topic() -> None:
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '[{"cluster_id": 0, "title": "삼성전자 실적", "summary": "호재.", '
        '"importance": "high", "tickers": ["005930"]}]'
    )
    svc = DedupeSummarizerService(client, "claude-haiku-4-5-20251001")
    m1 = _enriched("FastStockNews", 123, "삼성전자 실적 서프라이즈")
    topics = svc.summarize([PreCluster(representative=m1, members=[m1])])
    assert len(topics) == 1
    assert topics[0].title == "삼성전자 실적"
    assert topics[0].importance == "high"
    assert topics[0].tickers == ["005930"]
    assert topics[0].sources[0].channel_username == "FastStockNews"
    assert topics[0].sources[0].message_id == 123


def test_empty_clusters_returns_empty() -> None:
    svc = DedupeSummarizerService(MagicMock(), "model")
    assert svc.summarize([]) == []


def test_malformed_json_returns_empty() -> None:
    client = MagicMock()
    client.messages.create.return_value = _mock_response("this is not JSON")
    svc = DedupeSummarizerService(client, "model")
    m1 = _enriched("ch", 1, "text")
    topics = svc.summarize([PreCluster(representative=m1, members=[m1])])
    assert topics == []


def test_unknown_importance_defaults_to_medium() -> None:
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '[{"cluster_id": 0, "title": "T", "summary": "S", "importance": "critical", "tickers": []}]'
    )
    svc = DedupeSummarizerService(client, "model")
    m1 = _enriched("ch", 1, "x")
    topics = svc.summarize([PreCluster(representative=m1, members=[m1])])
    assert len(topics) == 1
    assert topics[0].importance == "medium"


def test_ignores_invalid_cluster_id() -> None:
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '[{"cluster_id": 99, "title": "T", "summary": "S", "importance": "medium", "tickers": []}]'
    )
    svc = DedupeSummarizerService(client, "model")
    m1 = _enriched("ch", 1, "x")
    topics = svc.summarize([PreCluster(representative=m1, members=[m1])])
    assert topics == []
