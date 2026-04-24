"""티커 추출기 단위 테스트: 정규식·사전·코인 키워드."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.services.ticker_extractor import TickerExtractor


def _mock_dict(name_to_code: dict[str, str]) -> MagicMock:
    m = MagicMock()
    m.code_of.side_effect = lambda n: name_to_code.get(n)
    m.name_of.side_effect = lambda c: next(
        (n for n, cc in name_to_code.items() if cc == c), None
    )
    m.names.return_value = list(name_to_code.keys())
    return m


def test_krx_6digit_code() -> None:
    d = _mock_dict({"삼성전자": "005930"})
    ext = TickerExtractor(d)
    out = ext.extract("오늘 005930 매수 추천")
    assert len(out) == 1
    assert out[0].code == "005930"
    assert out[0].market == "KR"
    assert out[0].name == "삼성전자"


def test_krx_name_match() -> None:
    d = _mock_dict({"삼성전자": "005930", "LG에너지솔루션": "373220"})
    ext = TickerExtractor(d)
    out = ext.extract("LG에너지솔루션이 상승세")
    codes = [t.code for t in out]
    assert "373220" in codes


def test_us_ticker_dollar_prefix() -> None:
    d = _mock_dict({})
    ext = TickerExtractor(d)
    out = ext.extract("$TSLA 호재 나왔음")
    assert any(t.code == "TSLA" and t.market == "US" for t in out)


def test_crypto_keyword() -> None:
    d = _mock_dict({})
    ext = TickerExtractor(d)
    out = ext.extract("비트코인이 10만 달러 돌파")
    assert any(t.code == "BTC/KRW" and t.market == "CRYPTO" for t in out)


def test_no_match_without_llm_returns_empty() -> None:
    d = _mock_dict({})
    ext = TickerExtractor(d, client=None, model=None)
    assert ext.extract("관련 종목 없음") == []


def test_7digit_not_matched() -> None:
    # KRX 코드는 정확히 6자리
    d = _mock_dict({})
    ext = TickerExtractor(d)
    out = ext.extract("거래대금 1234567 원")
    assert not any(t.market == "KR" for t in out)


def test_dedupe_same_code_same_market() -> None:
    d = _mock_dict({"삼성전자": "005930"})
    ext = TickerExtractor(d)
    out = ext.extract("005930 삼성전자 또 005930")
    kr_codes = [t for t in out if t.market == "KR"]
    assert len(kr_codes) == 1
