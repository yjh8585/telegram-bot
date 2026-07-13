"""텔레그램 채널 요약 봇 엔트리포인트.

사용 예:
    python -m src.main                        # 기본: --window auto
    python -m src.main --window morning       # 특정 슬롯 강제
    python -m src.main --dry-run              # DM 발송·state 갱신 생략
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from datetime import UTC, datetime, timedelta
from typing import cast

from anthropic import Anthropic
from loguru import logger
from sentence_transformers import SentenceTransformer

from src.config import Settings, get_settings
from src.dtos import ClusteredTopic, Market, OutboundBlock, RawMessage, Ticker
from src.logger import setup_logger
from src.repositories.state_repo import StateRepository
from src.repositories.telethon_repo import TelethonRepository
from src.services.article_fetcher import ArticleFetcher
from src.services.collector import CollectorService
from src.services.dedupe_summarizer import DedupeSummarizerService
from src.services.enrichment import EnrichmentService
from src.services.formatter import build_messages
from src.services.message_filter import filter_messages
from src.services.notifier import NotifierService
from src.services.pre_cluster import DEFAULT_MODEL_NAME, PreClusterService
from src.services.recent_dedup import RecentDedupService
from src.services.stock import StockService
from src.services.ticker_dict import TickerDict
from src.services.ticker_extractor import TickerExtractor
from src.services.vision import VisionService
from src.window import Window, WindowLabel, current_window, window_by_label

_WINDOW_CHOICES: tuple[str, ...] = ("auto", "morning", "late_morning", "afternoon", "evening")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Telegram 채널 요약 봇")
    p.add_argument("--window", choices=_WINDOW_CHOICES, default="auto")
    p.add_argument("--dry-run", action="store_true", help="DM 발송/state 갱신 생략")
    p.add_argument(
        "--no-commit",
        action="store_true",
        help="DM은 발송하되 last_seen 갱신 생략(테스트런용)",
    )
    return p.parse_args()


def _resolve_window(choice: str) -> Window:
    if choice == "auto":
        return current_window()
    return window_by_label(cast(WindowLabel, choice))


def _guess_market(code: str) -> Market:
    if code.isdigit() and len(code) == 6:
        return "KR"
    if "/" in code:
        return "CRYPTO"
    return "US"


def _build_blocks(topics: list[ClusteredTopic], stock: StockService) -> list[OutboundBlock]:
    blocks: list[OutboundBlock] = []
    for topic in topics:
        tickers = [Ticker(code=code, market=_guess_market(code)) for code in topic.tickers]
        quotes = stock.fetch_quotes(tickers)
        blocks.append(OutboundBlock(topic=topic, quotes=quotes))
    return blocks


def _analyze(
    settings: Settings,
    state: StateRepository,
    client: Anthropic,
    msgs: list[RawMessage],
    ticker_dict: TickerDict,
    ticker_extractor: TickerExtractor,
    model: SentenceTransformer,
) -> list[OutboundBlock]:
    """필터된 메시지를 enrichment → pre_cluster → summarize → stock 순으로 파이프라인."""
    article_fetcher = ArticleFetcher(state)
    vision = VisionService(client, settings.model, state)
    enrichment = EnrichmentService(article_fetcher, ticker_extractor, vision)
    pre_cluster = PreClusterService(settings.dedupe_threshold, model)
    summarizer = DedupeSummarizerService(client, settings.model)

    enriched = [enrichment.enrich(m) for m in msgs]
    clusters = pre_cluster.cluster(enriched)
    topics = summarizer.summarize(clusters)
    stock = StockService(ticker_dict)
    return _build_blocks(topics, stock)


def _dedup_recent(
    settings: Settings,
    state: StateRepository,
    model: SentenceTransformer,
    msgs: list[RawMessage],
) -> list[RawMessage]:
    """cross-run 중복 제거. 실패 시 graceful degrade(전체 유지)."""
    dedup = RecentDedupService(
        settings.recent_dedup_threshold, settings.recent_dedup_window_hours, state, model
    )
    try:
        return dedup.filter_new(msgs)
    except Exception as e:
        logger.error(f"recent-dedup 실패, 전체 유지: {e}")
        return msgs


def _process(
    settings: Settings,
    state: StateRepository,
    client: Anthropic,
    raw_msgs: list[RawMessage],
    window: Window,
) -> tuple[list[str], list[ClusteredTopic]]:
    """수집분을 필터·중복제거·분석해 (발송 메시지, 발송 토픽)을 반환."""
    if not raw_msgs:
        return build_messages(window, []), []
    ticker_dict = TickerDict(settings.state_db_path.parent)
    ticker_extractor = TickerExtractor(
        ticker_dict, client, settings.model, enable_llm_fallback=settings.enable_ticker_llm_fallback
    )
    kept_msgs = filter_messages(raw_msgs, ticker_extractor)
    if not kept_msgs:
        return build_messages(window, []), []
    model = SentenceTransformer(DEFAULT_MODEL_NAME)
    fresh_msgs = _dedup_recent(settings, state, model, kept_msgs)
    if not fresh_msgs:
        # 전부 최근에 다룬 주제 — "새 정보 없음" 정상 발송
        return build_messages(window, []), []
    blocks = _analyze(
        settings, state, client, fresh_msgs, ticker_dict, ticker_extractor, model
    )
    if not blocks:
        raise RuntimeError(
            f"분석 파이프라인 결과 없음 (중복제거 후 {len(fresh_msgs)}건 있음) "
            "— Claude 응답 또는 JSON 파싱 확인 필요"
        )
    return build_messages(window, blocks), [b.topic for b in blocks]


def _record_sent_topics(
    state: StateRepository, topics: list[ClusteredTopic], window_hours: int
) -> None:
    """발송 토픽의 제목+요약을 recent_topics에 기록하고 오래된 항목을 프루닝."""
    try:
        now = datetime.now(UTC)
        if topics:
            state.add_recent_topics([f"{t.title}\n{t.summary}" for t in topics], now)
            logger.info(f"recent_topics 기록 {len(topics)}건")
        state.prune_recent_topics(now - timedelta(hours=window_hours * 2))
    except Exception as e:
        logger.error(f"recent_topics 기록/프루닝 실패: {e}")


async def _deliver(
    settings: Settings,
    messages: list[str],
    dry_run: bool,
) -> None:
    if dry_run:
        # Windows cp949 터미널에서 이모지 인코딩 오류 방지
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        for i, m in enumerate(messages, 1):
            print(f"\n===== 메시지 {i}/{len(messages)} =====\n{m}")
        return
    async with NotifierService(settings.bot_token, settings.bot_chat_id) as notifier:
        await notifier.send_messages(messages)


async def _run(window: Window, dry_run: bool, no_commit: bool) -> None:
    settings = get_settings()
    logger.info(
        f"window={window.label} {window.header_text} dry_run={dry_run} no_commit={no_commit}"
    )

    state = StateRepository(settings.state_db_path)
    client = Anthropic(api_key=settings.anthropic_api_key)
    try:
        async with TelethonRepository(
            settings.tg_api_id, settings.tg_api_hash, settings.tg_session_string
        ) as tg:
            collector = CollectorService(tg, state)
            raw_msgs = await collector.collect(window)

        logger.info(f"총 {len(raw_msgs)}건 수집")

        messages, sent_topics = _process(settings, state, client, raw_msgs, window)
        await _deliver(settings, messages, dry_run)

        # last_seen·recent_topics 갱신: dry_run/no_commit이면 건너뜀
        if dry_run:
            return
        if no_commit:
            logger.info("--no-commit 옵션 — last_seen·recent_topics 갱신 생략")
            return
        if raw_msgs:
            collector.commit_last_seen(raw_msgs)
            logger.info("last_seen 갱신 완료")
        _record_sent_topics(state, sent_topics, settings.recent_dedup_window_hours)
    finally:
        state.close()


async def _report_error(exc: BaseException, tb: str, dry_run: bool) -> None:
    if dry_run:
        return
    try:
        settings = get_settings()
        async with NotifierService(settings.bot_token, settings.bot_chat_id) as notifier:
            await notifier.send_error(f"{exc}\n\n{tb[-2000:]}")
    except Exception as e:
        logger.error(f"에러 리포트 DM 실패: {e}")


async def _main() -> None:
    setup_logger()
    args = _parse_args()
    window = _resolve_window(args.window)
    try:
        await _run(window, args.dry_run, args.no_commit)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"오케스트레이션 실패: {e}")
        await _report_error(e, tb, args.dry_run)
        raise


if __name__ == "__main__":
    asyncio.run(_main())
