"""RawMessage → EnrichedMessage: 뉴스 본문·이미지 설명·티커 추출을 조합."""
from __future__ import annotations

from src.dtos import ArticleBody, EnrichedMessage, RawMessage
from src.services.article_fetcher import ArticleFetcher
from src.services.ticker_extractor import TickerExtractor
from src.services.vision import VisionService


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
        articles = self._collect_articles(msg.urls)
        image_desc = self._describe_image(msg)
        combined_text = _build_combined_text(msg, articles, image_desc)
        tickers = self._tickers.extract(combined_text)
        return EnrichedMessage(
            raw=msg,
            article_bodies=articles,
            image_description=image_desc,
            tickers=tickers,
        )

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


def _build_combined_text(
    msg: RawMessage, articles: list[ArticleBody], image_desc: str | None
) -> str:
    parts: list[str] = [msg.text]
    if image_desc:
        parts.append(image_desc)
    for art in articles:
        if art.title:
            parts.append(art.title)
        if art.body:
            parts.append(art.body)
    return "\n".join(p for p in parts if p).strip()
