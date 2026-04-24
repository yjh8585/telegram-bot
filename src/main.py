"""텔레그램 채널 요약 봇 엔트리포인트.

사용 예:
    python -m src.main                        # 기본: --window auto
    python -m src.main --window morning       # 특정 슬롯 강제
    python -m src.main --dry-run              # DM 발송·state 갱신 생략
"""

from __future__ import annotations

import argparse
import asyncio
import traceback
from typing import cast

from anthropic import Anthropic
from loguru import logger

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
from src.services.notifier import NotifierService
from src.services.pre_cluster import PreClusterService
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
    raw_msgs: list[RawMessage],
) -> list[OutboundBlock]:
    """수집된 원본 메시지를 enrichment → pre_cluster → summarize → stock 순으로 파이프라인."""
    ticker_dict = TickerDict(settings.state_db_path.parent)
    article_fetcher = ArticleFetcher(state)
    vision = VisionService(client, settings.model, state)
    ticker_extractor = TickerExtractor(ticker_dict, client, settings.model)
    enrichment = EnrichmentService(article_fetcher, ticker_extractor, vision)
    pre_cluster = PreClusterService(settings.dedupe_threshold)
    summarizer = DedupeSummarizerService(client, settings.model)
    stock = StockService()

    enriched = [enrichment.enrich(m) for m in raw_msgs]
    clusters = pre_cluster.cluster(enriched)
    topics = summarizer.summarize(clusters)
    return _build_blocks(topics, stock)


async def _deliver(settings: Settings, messages: list[str], dry_run: bool) -> None:
    if dry_run:
        for i, m in enumerate(messages, 1):
            print(f"\n===== 메시지 {i}/{len(messages)} =====\n{m}")
        return
    notifier = NotifierService(settings.bot_token, settings.bot_chat_id)
    await notifier.send_messages(messages)


async def _run(window: Window, dry_run: bool) -> None:
    settings = get_settings()
    logger.info(f"window={window.label} {window.header_text} dry_run={dry_run}")

    state = StateRepository(settings.state_db_path)
    client = Anthropic(api_key=settings.anthropic_api_key)
    try:
        async with TelethonRepository(
            settings.tg_api_id, settings.tg_api_hash, settings.tg_session_string
        ) as tg:
            collector = CollectorService(tg, state)
            raw_msgs = await collector.collect(window)

        logger.info(f"총 {len(raw_msgs)}건 수집")
        blocks = _analyze(settings, state, client, raw_msgs) if raw_msgs else []
        messages = build_messages(window, blocks)
        await _deliver(settings, messages, dry_run)

        if not dry_run and raw_msgs:
            collector.commit_last_seen(raw_msgs)
            logger.info("last_seen 갱신 완료")
    finally:
        state.close()


async def _report_error(exc: BaseException, tb: str, dry_run: bool) -> None:
    if dry_run:
        return
    try:
        settings = get_settings()
        notifier = NotifierService(settings.bot_token, settings.bot_chat_id)
        await notifier.send_error(f"{exc}\n\n{tb[-2000:]}")
    except Exception as e:
        logger.error(f"에러 리포트 DM 실패: {e}")


async def _main() -> None:
    setup_logger()
    args = _parse_args()
    window = _resolve_window(args.window)
    try:
        await _run(window, args.dry_run)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"오케스트레이션 실패: {e}")
        await _report_error(e, tb, args.dry_run)
        raise


if __name__ == "__main__":
    asyncio.run(_main())
