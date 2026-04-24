"""StockService: FDR mock으로 시세·등락률·실패 graceful degrade 검증."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.dtos import Ticker
from src.services.stock import StockService


def _df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-04-18", periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes}, index=idx)


def test_kr_ticker_ok() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch("src.services.stock.fdr.DataReader", return_value=_df([70000, 71400])):
        quotes = svc.fetch_quotes([Ticker(code="005930", market="KR", name="삼성전자")])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.code == "005930"
    assert q.price == 71400
    assert q.currency == "KRW"
    assert q.change_pct is not None
    assert round(q.change_pct, 2) == 2.0


def test_us_ticker_returns_usd() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch("src.services.stock.fdr.DataReader", return_value=_df([100.0, 105.0])):
        quotes = svc.fetch_quotes([Ticker(code="TSLA", market="US")])
    assert quotes[0].currency == "USD"


def test_crypto_returns_krw() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch("src.services.stock.fdr.DataReader", return_value=_df([100000.0, 101000.0])):
        quotes = svc.fetch_quotes([Ticker(code="BTC/KRW", market="CRYPTO")])
    assert quotes[0].currency == "KRW"


def test_empty_df_returns_none() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch("src.services.stock.fdr.DataReader", return_value=pd.DataFrame()):
        quotes = svc.fetch_quotes([Ticker(code="005930", market="KR")])
    assert quotes == []


def test_single_row_no_change_pct() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch("src.services.stock.fdr.DataReader", return_value=_df([100.0])):
        quotes = svc.fetch_quotes([Ticker(code="005930", market="KR")])
    assert quotes[0].change_pct is None


def test_dedupe_same_code_market() -> None:
    svc = StockService(max_retries=1, wait_base=0)
    with patch(
        "src.services.stock.fdr.DataReader", return_value=_df([100.0, 101.0])
    ) as m:
        svc.fetch_quotes(
            [
                Ticker(code="005930", market="KR"),
                Ticker(code="005930", market="KR", name="삼성전자"),
            ]
        )
    assert m.call_count == 1


def test_exception_returns_empty() -> None:
    svc = StockService(max_retries=2, wait_base=0)
    with patch(
        "src.services.stock.fdr.DataReader", side_effect=RuntimeError("network err")
    ) as m:
        quotes = svc.fetch_quotes([Ticker(code="005930", market="KR")])
    assert quotes == []
    # max_retries=2 → 총 2회 호출
    assert m.call_count == 2
