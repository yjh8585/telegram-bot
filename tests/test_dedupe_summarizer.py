"""DedupeSummarizerService: Claude 응답 파싱·빈 입력·잘못된 JSON 처리."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.dtos import EnrichedMessage, PreCluster, RawMessage
from src.services.dedupe_summarizer import DedupeSummarizerService


def _enriched(channel: str, mid: int, text: str) -> EnrichedMessage:
    return EnrichedMessage(
        raw=RawMessage(
            channel_username=channel,
            message_id=mid,
            posted_at=datetime(2026, 4, 24, tzinfo=UTC),
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


def test_empty_title_or_summary_filtered() -> None:
    """무의미 토픽(빈 title/summary)은 출력에서 제외되어야 한다."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '['
        '{"cluster_id": 0, "title": "", "summary": "S", "importance": "low", "tickers": []},'
        '{"cluster_id": 0, "title": "T", "summary": "", "importance": "low", "tickers": []},'
        '{"cluster_id": 0, "title": "정상", "summary": "내용", "importance": "low", "tickers": []}'
        ']'
    )
    svc = DedupeSummarizerService(client, "model")
    m1 = _enriched("ch", 1, "x")
    topics = svc.summarize([PreCluster(representative=m1, members=[m1])])
    assert len(topics) == 1
    assert topics[0].title == "정상"


def test_batches_when_over_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """클러스터가 배치 상한을 넘으면 나눠 호출하고 전체 토픽을 모아 반환한다."""
    import src.services.dedupe_summarizer as mod

    monkeypatch.setattr(mod, "_MAX_CLUSTERS_PER_CALL", 2)
    client = MagicMock()
    # 3개 클러스터, 배치 2 → 2회 호출(배치별 cluster_id는 0부터)
    client.messages.create.side_effect = [
        _mock_response(
            '[{"cluster_id": 0, "title": "A", "summary": "s", "importance": "low", "tickers": []},'
            '{"cluster_id": 1, "title": "B", "summary": "s", "importance": "low", "tickers": []}]'
        ),
        _mock_response(
            '[{"cluster_id": 0, "title": "C", "summary": "s", "importance": "low", "tickers": []}]'
        ),
    ]
    svc = DedupeSummarizerService(client, "model")
    clusters = []
    for mid in (1, 2, 3):
        m = _enriched("ch", mid, f"text {mid}")
        clusters.append(PreCluster(representative=m, members=[m]))
    topics = svc.summarize(clusters)
    assert client.messages.create.call_count == 2
    assert [t.title for t in topics] == ["A", "B", "C"]
    # 두 번째 배치의 cluster_id 0 → 전역 clusters[2](message_id 3)로 매핑
    c_topic = next(t for t in topics if t.title == "C")
    assert c_topic.sources[0].message_id == 3


def test_one_failed_batch_does_not_kill_others(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """한 배치 호출이 실패해도 나머지 배치 결과는 유지된다(graceful degrade)."""
    import src.services.dedupe_summarizer as mod

    monkeypatch.setattr(mod, "_MAX_CLUSTERS_PER_CALL", 1)
    client = MagicMock()
    client.messages.create.side_effect = [
        RuntimeError("API 오류"),
        _mock_response(
            '[{"cluster_id": 0, "title": "B", "summary": "s", "importance": "low", "tickers": []}]'
        ),
    ]
    svc = DedupeSummarizerService(client, "model")
    clusters = []
    for mid in (1, 2):
        m = _enriched("ch", mid, f"text {mid}")
        clusters.append(PreCluster(representative=m, members=[m]))
    topics = svc.summarize(clusters)
    assert [t.title for t in topics] == ["B"]


def test_same_channel_sources_deduped() -> None:
    """같은 채널의 여러 멤버가 있어도 출처는 채널당 1개로 축약."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '[{"cluster_id": 0, "title": "T", "summary": "S", "importance": "medium", "tickers": []}]'
    )
    svc = DedupeSummarizerService(client, "model")
    members = [_enriched("darthacking", i, f"text {i}") for i in (101, 102, 103, 104, 105)]
    cluster = PreCluster(representative=members[0], members=members)
    topics = svc.summarize([cluster])
    assert len(topics) == 1
    assert len(topics[0].sources) == 1
    assert topics[0].sources[0].channel_username == "darthacking"
    # 첫 등장 멤버의 message_id가 채택되어야 함
    assert topics[0].sources[0].message_id == 101


def test_cap_clusters_keeps_top_by_member_count() -> None:
    """max_topics>0이면 멤버수 상위 N개만 남기고 원래 순서를 보존한다."""
    from src.services.dedupe_summarizer import _cap_clusters

    def _cluster(n_members: int) -> PreCluster:
        ms = [_enriched("ch", i, "x") for i in range(1, n_members + 1)]
        return PreCluster(representative=ms[0], members=ms)

    clusters = [_cluster(1), _cluster(5), _cluster(2), _cluster(3)]
    kept = _cap_clusters(clusters, max_topics=2)
    assert [len(c.members) for c in kept] == [5, 3]


def test_cap_clusters_off_or_under_limit_returns_same() -> None:
    from src.services.dedupe_summarizer import _cap_clusters

    m = _enriched("ch", 1, "x")
    clusters = [PreCluster(representative=m, members=[m])]
    assert _cap_clusters(clusters, max_topics=0) is clusters
    assert _cap_clusters(clusters, max_topics=5) is clusters


def test_rep_text_limit_truncates_payload() -> None:
    from src.services.dedupe_summarizer import _build_user_payload

    m = _enriched("ch", 1, "가" * 3000)
    payload = _build_user_payload([PreCluster(representative=m, members=[m])], rep_text_limit=100)
    assert "가" * 100 in payload
    assert "가" * 101 not in payload
