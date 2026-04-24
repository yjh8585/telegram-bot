"""티커 추출: 1차 정규식·KRX 종목명 사전, 2차 Claude JSON 폴백."""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic
from loguru import logger

from src.dtos import Ticker
from src.services.ticker_dict import TickerDict

_KR_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_US_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")

# 텍스트에서 자주 언급되는 주요 코인·해당 FDR 심볼
_CRYPTO_KEYWORDS: dict[str, str] = {
    "비트코인": "BTC/KRW",
    "BTC": "BTC/KRW",
    "이더리움": "ETH/KRW",
    "이더": "ETH/KRW",
    "ETH": "ETH/KRW",
    "리플": "XRP/KRW",
    "XRP": "XRP/KRW",
    "솔라나": "SOL/KRW",
    "SOL": "SOL/KRW",
    "도지": "DOGE/KRW",
    "DOGE": "DOGE/KRW",
}

_MIN_NAME_LEN = 2
_LLM_MAX_TOKENS = 400
_LLM_PROMPT = (
    "다음 한국어 텍스트에서 언급된 주식·암호자산 티커를 모두 찾아 JSON 배열로만 응답하세요.\n"
    '각 원소는 {"code": "...", "market": "KR|US|CRYPTO", "name": "..."} 구조.\n'
    "- 한국 종목: code는 6자리 숫자, name은 한국어 종목명.\n"
    "- 미국 종목: code는 티커 심볼(대문자), name은 기업명(영문 또는 한국어).\n"
    "- 암호자산: code는 '<심볼>/KRW' (예: BTC/KRW).\n"
    "중복 없이, 실제 언급된 것만. 불명확하면 포함하지 마세요. JSON 외 텍스트 금지.\n\n"
    "텍스트:\n"
)


class TickerExtractor:
    """정규식 + KRX 종목명 사전으로 먼저 추출, 0건일 때만 LLM 폴백."""

    def __init__(
        self,
        ticker_dict: TickerDict,
        client: Anthropic | None = None,
        model: str | None = None,
    ) -> None:
        self._dict = ticker_dict
        self._client = client
        self._model = model

    def extract(self, text: str) -> list[Ticker]:
        if not text:
            return []
        tickers: list[Ticker] = []
        seen: set[tuple[str, str]] = set()

        def add(code: str, market: str, name: str | None) -> None:
            key = (code, market)
            if key in seen:
                return
            seen.add(key)
            tickers.append(Ticker(code=code, market=market, name=name))  # type: ignore[arg-type]

        for code in _KR_CODE_RE.findall(text):
            add(code, "KR", self._dict.name_of(code))

        for sym in _US_TICKER_RE.findall(text):
            add(sym, "US", None)

        for kw, code in _CRYPTO_KEYWORDS.items():
            if kw in text:
                add(code, "CRYPTO", kw)

        for name in self._dict.names():
            if len(name) >= _MIN_NAME_LEN and name in text:
                code = self._dict.code_of(name)
                if code:
                    add(code, "KR", name)

        if tickers:
            return tickers
        return self._llm_fallback(text)

    def _llm_fallback(self, text: str) -> list[Ticker]:
        if self._client is None or not self._model:
            return []
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_LLM_MAX_TOKENS,
                messages=[{"role": "user", "content": _LLM_PROMPT + text}],
            )
        except Exception as e:
            logger.warning(f"ticker LLM 폴백 실패: {e}")
            return []

        raw = _extract_text_block(response)
        return _parse_ticker_json(raw)


def _extract_text_block(msg: Any) -> str:
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _parse_ticker_json(raw: str) -> list[Ticker]:
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        arr = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[Ticker] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        market = str(item.get("market") or "").strip().upper()
        if market not in ("KR", "US", "CRYPTO") or not code:
            continue
        name = item.get("name")
        out.append(Ticker(code=code, market=market, name=name if name else None))  # type: ignore[arg-type]
    return out
