"""티커 추출: 1차 정규식·KRX 종목명 사전, 2차 Claude JSON 폴백."""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic
from loguru import logger

from src.dtos import Ticker
from src.logger import log_api_usage
from src.services.ticker_dict import TickerDict

_KR_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_US_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
# 한글·영문·숫자가 인접하면 단어 경계로 보지 않음. (Python `\b`는 한글 미지원)
_BOUNDARY_CHAR_RE = re.compile(r"[가-힣A-Za-z0-9]")
# 우측 경계가 한글일 때 인정하는 한국어 조사(1글자·2글자). 조사 뒤가 비단어여야 경계로 인정.
_KO_PARTICLES_1 = frozenset(
    {"의", "이", "가", "을", "를", "은", "는", "에", "도", "만", "과", "와", "로", "라", "야", "여"}
)
_KO_PARTICLES_2 = frozenset({"에서", "에는", "에도", "으로", "라는", "라고", "이라", "에게"})

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

_MIN_NAME_LEN = 3  # 2자 이하 한국어는 일반 단어(남성·레이 등)와 구별 불가능해 false positive 발생
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
        enable_llm_fallback: bool = True,
    ) -> None:
        self._dict = ticker_dict
        self._client = client
        self._model = model
        self._enable_llm_fallback = enable_llm_fallback

    def extract(self, text: str) -> list[Ticker]:
        if not text:
            return []
        tickers = self.detect_without_llm(text)
        if tickers:
            return tickers
        return self._llm_fallback(text)

    def detect_without_llm(self, text: str) -> list[Ticker]:
        """정규식·KRX 사전·코인 키워드로만 티커 추출(LLM 폴백 미사용). 사전 필터용."""
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
            if len(name) < _MIN_NAME_LEN:
                continue
            if not _has_word_boundary_match(text, name):
                continue
            code = self._dict.code_of(name)
            if code:
                add(code, "KR", name)

        return tickers

    def has_ticker(self, text: str) -> bool:
        """LLM 없이 종목·코인이 검출되는지 여부(사전 필터용)."""
        return bool(self.detect_without_llm(text))

    def _llm_fallback(self, text: str) -> list[Ticker]:
        if not self._enable_llm_fallback or self._client is None or not self._model:
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

        log_api_usage("ticker_fallback", response)
        raw = _extract_text_block(response)
        return _parse_ticker_json(raw)


def _right_is_word_boundary(text: str, idx: int) -> bool:
    """우측 경계 검사: 비단어이거나 한국어 조사(+비단어) 패턴이면 경계로 인정.

    예) "SK하이닉스의 메모리" → '의' 뒤가 공백이라 경계로 인정.
        "선진국 지수" 안의 '선진' → '국'은 조사 아님 → 경계 아님(합성어).
    """
    if idx >= len(text):
        return True
    ch = text[idx]
    if not _BOUNDARY_CHAR_RE.match(ch):
        return True
    # 2글자 조사 우선 매칭(에서·으로 등). 그 뒤가 비단어여야 함.
    if text[idx : idx + 2] in _KO_PARTICLES_2:
        end = idx + 2
        nxt = text[end] if end < len(text) else ""
        return not (nxt and _BOUNDARY_CHAR_RE.match(nxt))
    if ch in _KO_PARTICLES_1:
        end = idx + 1
        nxt = text[end] if end < len(text) else ""
        return not (nxt and _BOUNDARY_CHAR_RE.match(nxt))
    return False


def _has_word_boundary_match(text: str, name: str) -> bool:
    """`name` 이 `text` 안에 단어 경계로 등장하는지 검사.

    좌측 인접 문자가 한글/영문/숫자면 합성어 일부로 보고 거부.
    우측은 비단어이거나 한국어 조사(+비단어) 패턴이면 경계로 인정.
    예) "SK하이닉스" 안의 "이닉스"는 좌측이 '하'(한글)이라 매칭되지 않음.
    """
    name_len = len(name)
    pos = text.find(name)
    while pos != -1:
        left = text[pos - 1] if pos > 0 else ""
        left_is_word = bool(left and _BOUNDARY_CHAR_RE.match(left))
        if not left_is_word and _right_is_word_boundary(text, pos + name_len):
            return True
        pos = text.find(name, pos + 1)
    return False


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
