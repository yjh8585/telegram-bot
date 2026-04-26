"""RawMessage → EnrichedMessage: 뉴스 본문·이미지 설명·티커 추출을 조합."""

from __future__ import annotations

from src.dtos import ArticleBody, EnrichedMessage, RawMessage
from src.services.article_fetcher import ArticleFetcher
from src.services.ticker_extractor import TickerExtractor
from src.services.vision import VisionService

# 텍스트가 이 길이 미만이고 photo·URL도 없으면 처리할 내용 없음으로 판단
_MIN_CONTENT_LEN = 10


class EnrichmentService:
    """단일 RawMessage에 대해 article·vision·ticker를 부착한 EnrichedMessage를 반환."""

    def __init__(
        self,
        article_fetcher: ArticleFetcher,
        ticker_extractor: TickerExtractor,
        vision_service: VisionService | None = None,
    ) -> None:
        self._articles = article_fetcher
        self._tickers = ticker_extractor
        self._vision = vision_service

    def enrich(self, msg: RawMessage) -> EnrichedMessage:
        # 빈 메시지(광고·이모지·스티커 등): article·vision·ticker 처리 전부 생략
        if len(msg.text.strip()) < _MIN_CONTENT_LEN and not msg.photo_sha1 and not msg.urls:
            return EnrichedMessage(raw=msg)
        articles = self._collect_articles(msg.urls)
        image_desc = self._describe_image(msg)
        # EnrichedMessage.combined_text property를 통해 임베딩·LLM용 통합 텍스트 생성
        enriched = EnrichedMessage(raw=msg, article_bodies=articles, image_description=image_desc)
        enriched.tickers = self._tickers.extract(enriched.combined_text)
        return enriched

    def _collect_articles(self, urls: list[str]) -> list[ArticleBody]:
        out: list[ArticleBody] = []
        for url in urls:
            body = self._articles.fetch(url)
            if body:
                out.append(body)
        return out

    def _describe_image(self, msg: RawMessage) -> str | None:
        if self._vision is None or not msg.photo_sha1 or not msg.photo_bytes:
            return None
        return self._vision.describe(msg.photo_sha1, msg.photo_bytes)
