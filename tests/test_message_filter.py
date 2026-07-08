"""저가치 메시지 사전 필터 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.dtos import RawMessage
from src.services.message_filter import KEEP_MIN_TEXT_LEN, filter_messages, should_keep
from src.services.ticker_extractor import TickerExtractor


def _mock_dict(name_to_code: dict[str, str]) -> MagicMock:
    m = MagicMock()
    m.code_of.side_effect = lambda n: name_to_code.get(n)
    m.name_of.side_effect = lambda c: next((n for n, cc in name_to_code.items() if cc == c), None)
    m.names.return_value = list(name_to_code.keys())
    return m


def _ext(names: dict[str, str] | None = None) -> TickerExtractor:
    # client=None → LLM 폴백 비활성. 필터는 어차피 has_ticker(무-LLM)만 사용.
    return TickerExtractor(_mock_dict(names or {}), client=None, model=None)


def _msg(
    text: str = "",
    urls: list[str] | None = None,
    photo: bool = False,
    mid: int = 1,
) -> RawMessage:
    return RawMessage(
        channel_username="ch",
        message_id=mid,
        posted_at=datetime(2026, 7, 8, tzinfo=UTC),
        text=text,
        urls=urls or [],
        photo_sha1="abc" if photo else None,
    )


def test_keep_when_has_ticker_code() -> None:
    keep, reason = should_keep(_msg("오늘 005930 흐름 좋네"), _ext({"삼성전자": "005930"}))
    assert keep is True
    assert reason == "ticker"


def test_keep_when_has_url() -> None:
    keep, reason = should_keep(
        _msg("속보", urls=["https://n.news.naver.com/x"]), _ext()
    )
    assert keep is True
    assert reason == "url"


def test_keep_long_commentary_without_ticker_or_url() -> None:
    text = "코스피 급락 코멘트 - 저점 판단 기준과 반등 트리거를 정리해서 보내드립니다 참고만"
    assert len(text) >= KEEP_MIN_TEXT_LEN
    keep, reason = should_keep(_msg(text), _ext())
    assert keep is True
    assert reason == "long_text"


def test_drop_short_chatter() -> None:
    keep, reason = should_keep(_msg("전멸..."), _ext())
    assert keep is False
    assert reason == "no_signal"


def test_keep_photo_with_ticker_caption() -> None:
    keep, reason = should_keep(_msg("삼성전자 일봉", photo=True), _ext({"삼성전자": "005930"}))
    assert keep is True
    assert reason == "ticker"


def test_keep_photo_with_long_analyst_caption() -> None:
    # 종목코드 없는 긴 시황·수급 캡션 차트는 보존(텍스트와 대칭)
    text = "소방수(기관) 투입 - 7월 들어 장중 하방 변동성이 확대되는 시점마다 기관이 순매수로 방어"
    assert len(text) >= KEEP_MIN_TEXT_LEN
    keep, reason = should_keep(_msg(text, photo=True), _ext())
    assert keep is True
    assert reason == "long_text"


def test_drop_photo_with_short_chatter_caption() -> None:
    keep, reason = should_keep(_msg("전멸... ㅜㅜ", photo=True), _ext())
    assert keep is False
    assert reason == "photo_short"


def test_drop_photo_without_caption() -> None:
    keep, reason = should_keep(_msg("", photo=True), _ext())
    assert keep is False
    assert reason == "photo_short"


def test_filter_messages_partitions_and_counts() -> None:
    msgs = [
        _msg("005930 좋다", mid=1),  # keep ticker
        _msg("ㅋㅋ", mid=2),  # drop
        _msg("속보", urls=["https://x"], mid=3),  # keep url
    ]
    kept = filter_messages(msgs, _ext({"삼성전자": "005930"}))
    assert [m.message_id for m in kept] == [1, 3]
