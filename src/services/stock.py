"""FinanceDataReader 기반 시세 조회. 실패 시 graceful degrade(해당 종목 생략)."""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Literal, cast

import FinanceDataReader as fdr
import pandas as pd
from loguru import logger

from src.dtos import StockQuote, Ticker
from src.services.ticker_dict import TickerDict

_LOOKBACK_DAYS = 7
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_WAIT_BASE = 0.5
_MAX_WAIT = 10.0

Currency = Literal["KRW", "USD"]


def _currency_of(market: str) -> Currency:
    # 코인은 FDR 조회 시 '<SYM>/KRW' 형식이라 KRW 기준.
    return "USD" if market == "US" else "KRW"


class StockService:
    """Ticker 리스트 → StockQuote 리스트. 같은 (code, market)은 1회만 조회."""

    def __init__(
        self,
        ticker_dict: TickerDict | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        wait_base: float = _DEFAULT_WAIT_BASE,
    ) -> None:
        self._ticker_dict = ticker_dict
        self._max_retries = max_retries
        self._wait_base = wait_base

    def fetch_quotes(self, tickers: list[Ticker]) -> list[StockQuote]:
        out: list[StockQuote] = []
        seen: set[tuple[str, str]] = set()
        for t in tickers:
            key = (t.market, t.code)
            if key in seen:
                continue
            seen.add(key)
            quote = self._fetch_one(t)
            if quote is not None:
                out.append(quote)
        return out

    def _fetch_one(self, t: Ticker) -> StockQuote | None:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._build_quote(t)
            except Exception as e:  # 네트워크·파싱 등 외부 오류 포괄
                last_exc = e
                if attempt < self._max_retries - 1:
                    wait = min(self._wait_base * (2**attempt), _MAX_WAIT)
                    time.sleep(wait)
        logger.warning(f"시세 조회 실패 {t.market}:{t.code} err={last_exc}")
        return None

    def _build_quote(self, t: Ticker) -> StockQuote | None:
        today = date.today()
        since = today - timedelta(days=_LOOKBACK_DAYS)
        df: pd.DataFrame = fdr.DataReader(t.code, since, today + timedelta(days=1))
        if df.empty or "Close" not in df.columns:
            return None
        last = df.iloc[-1]
        price = float(last["Close"])
        change_pct = _change_pct(df)
        as_of = _last_date(df, today)

        # KR 종목: TickerDict에서 종목명·거래소 보완 (주입된 경우에만)
        name = t.name
        exchange: str | None = None
        if t.market == "KR" and self._ticker_dict is not None:
            name = name or self._ticker_dict.name_of(t.code)
            exchange = self._ticker_dict.exchange_of(t.code)
            if not name:
                logger.warning(f"종목명 조회 실패: {t.code} — TickerDict에 해당 코드 없음")

        return StockQuote(
            code=t.code,
            name=name,
            exchange=exchange,
            price=price,
            change_pct=change_pct,
            currency=_currency_of(t.market),
            as_of=as_of,
        )


def _change_pct(df: pd.DataFrame) -> float | None:
    if len(df) < 2:
        return None
    prev = float(df.iloc[-2]["Close"])
    if prev == 0:
        return None
    curr = float(df.iloc[-1]["Close"])
    return (curr - prev) / prev * 100


def _last_date(df: pd.DataFrame, fallback: date) -> date:
    idx = df.index[-1]
    if hasattr(idx, "date"):
        return cast(date, idx.date())
    return fallback
