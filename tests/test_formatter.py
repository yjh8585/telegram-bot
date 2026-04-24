"""formatter: MarkdownV2 이스케이프·토픽 조립·분할 검증 (syrupy 스냅샷 포함)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.dtos import ClusteredTopic, OutboundBlock, SourceRef, StockQuote
from src.services.formatter import build_messages, escape_md
from src.window import Window

KST = ZoneInfo("Asia/Seoul")


def _window_evening() -> Window:
    return Window(
        label="evening",
        start=datetime(2026, 4, 24, 15, 0, tzinfo=KST),
        end=datetime(2026, 4, 24, 18, 0, tzinfo=KST),
    )


def _block(
    title: str,
    summary: str,
    quotes: list[StockQuote] | None = None,
    importance: str = "medium",
    sources: list[SourceRef] | None = None,
) -> OutboundBlock:
    return OutboundBlock(
        topic=ClusteredTopic(
            title=title,
            summary=summary,
            importance=importance,  # type: ignore[arg-type]
            sources=sources or [SourceRef(channel_username="FastStockNews", message_id=123)],
            tickers=["005930"],
        ),
        quotes=quotes or [],
    )


# --- escape_md ---------------------------------------------------------


def test_escape_md_all_reserved() -> None:
    # 예약 문자 샘플 모두 이스케이프
    assert escape_md("1.0+2") == r"1\.0\+2"
    assert escape_md("a_b*c") == r"a\_b\*c"
    assert escape_md("!") == r"\!"


def test_escape_md_preserves_plain_text() -> None:
    assert escape_md("삼성전자 실적") == "삼성전자 실적"


# --- build_messages 기본 동작 -----------------------------------------


def test_empty_blocks_returns_info_message() -> None:
    out = build_messages(_window_evening(), [])
    assert len(out) == 1
    assert "해당 구간에 수집된 새 정보가 없습니다" in out[0]


def test_topic_contains_title_summary_sources() -> None:
    block = _block(
        "삼성전자 실적 호조",
        "영업이익 20% 증가.",
        sources=[
            SourceRef(channel_username="FastStockNews", message_id=1),
            SourceRef(channel_username="Yeouido_Lab", message_id=2),
        ],
    )
    out = build_messages(_window_evening(), [block])
    assert len(out) == 1
    msg = out[0]
    assert "삼성전자 실적 호조" in msg
    assert "영업이익 20% 증가" in msg
    assert "https://t.me/FastStockNews/1" in msg
    assert "https://t.me/Yeouido_Lab/2" in msg


def test_topic_with_quote_formats_price_and_change() -> None:
    quote = StockQuote(
        code="005930",
        name="삼성전자",
        price=72400,
        change_pct=1.23,
        currency="KRW",
        as_of=date(2026, 4, 24),
    )
    block = _block("삼성전자", "요약", quotes=[quote])
    out = build_messages(_window_evening(), [block])
    msg = out[0]
    assert "72,400원" in msg
    # +1.2% → 이스케이프 됨
    assert r"\+1\.2%" in msg


def test_split_when_too_long() -> None:
    long_summary = "가" * 1500
    blocks = [_block(f"토픽 {i}", long_summary) for i in range(5)]
    out = build_messages(_window_evening(), blocks)
    assert len(out) >= 2
    for m in out:
        assert len(m) <= 4096


# --- 스냅샷 -----------------------------------------------------------


def test_formatter_snapshot(snapshot) -> None:  # type: ignore[no-untyped-def]
    block = _block(
        "삼성전자 4Q 실적 서프라이즈",
        "전년 대비 20% 증가. 반도체 반등이 주효.",
        quotes=[
            StockQuote(
                code="005930",
                name="삼성전자",
                price=72400,
                change_pct=1.2,
                currency="KRW",
                as_of=date(2026, 4, 24),
            )
        ],
        importance="high",
    )
    assert build_messages(_window_evening(), [block]) == snapshot
