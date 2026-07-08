"""저가치 메시지 사전 필터: enrichment 전에 신호 없는 메시지를 제거해 비용 절감.

판정 규칙(위에서부터, 먼저 걸리는 규칙이 결과 결정):
1. 종목/코인 검출(무-LLM) → 유지(ticker). 사진 캡션도 text에 담겨 여기서 처리됨.
2. 뉴스 URL 있음 → 유지(url).
3. 본문 길이 ≥ KEEP_MIN_TEXT_LEN → 유지(long_text). 사진·텍스트 공통(대칭):
   차트에 붙은 시황·수급·애널리스트 코멘트(종목코드 없는 긴 캡션)를 보존한다.
4. 사진 있음(1~3 불충족, 즉 짧거나 빈 캡션) → 제거(photo_short).
5. 그 외(짧은 텍스트 잡담) → 제거(no_signal).
"""

from __future__ import annotations

from loguru import logger

from src.dtos import RawMessage
from src.services.ticker_extractor import TickerExtractor

# 종목·URL·사진이 없어도 이 길이 이상이면 시황·애널리스트 코멘트로 보고 유지
KEEP_MIN_TEXT_LEN = 40

_DROP_LOG_SNIPPET = 40  # 제거 로그에 남길 본문 길이


def should_keep(msg: RawMessage, ticker_extractor: TickerExtractor) -> tuple[bool, str]:
    """메시지를 파이프라인에 태울지 여부와 사유를 반환."""
    text = msg.text or ""
    if ticker_extractor.has_ticker(text):
        return True, "ticker"
    if msg.urls:
        return True, "url"
    if len(text.strip()) >= KEEP_MIN_TEXT_LEN:
        return True, "long_text"
    if msg.photo_sha1:
        return False, "photo_short"
    return False, "no_signal"


def filter_messages(
    messages: list[RawMessage], ticker_extractor: TickerExtractor
) -> list[RawMessage]:
    """유지 대상만 반환. 제거 건은 사유·본문 일부를 INFO 로그로 남긴다."""
    kept: list[RawMessage] = []
    dropped = 0
    for msg in messages:
        keep, reason = should_keep(msg, ticker_extractor)
        if keep:
            kept.append(msg)
            continue
        dropped += 1
        snippet = (msg.text or "").replace("\n", " ")[:_DROP_LOG_SNIPPET]
        logger.info(f"[filter] drop ({msg.channel_username}) reason={reason} | {snippet}")
    logger.info(f"filter: 총 {len(messages)}건 → 유지 {len(kept)}건(제거 {dropped}건)")
    return kept
