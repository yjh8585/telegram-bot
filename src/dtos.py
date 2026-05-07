"""pydantic v2 기반 DTO."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Market = Literal["KR", "US", "CRYPTO"]
Importance = Literal["high", "medium", "low"]


class RawMessage(BaseModel):
    """Telethon이 수집한 원본 메시지."""

    channel_username: str
    message_id: int
    posted_at: datetime  # UTC aware
    text: str = ""
    photo_sha1: str | None = None
    photo_caption: str | None = None
    # vision 입력용 메모리 바이트. 로그·직렬화 제외.
    photo_bytes: bytes | None = Field(default=None, exclude=True, repr=False)
    urls: list[str] = Field(default_factory=list)

    @property
    def source_url(self) -> str:
        return f"https://t.me/{self.channel_username}/{self.message_id}"


class ArticleBody(BaseModel):
    """뉴스 URL을 trafilatura로 추출한 본문."""

    url: str
    title: str = ""
    body: str = ""


class Ticker(BaseModel):
    """메시지에서 추출된 종목/자산 식별자."""

    code: str
    market: Market
    name: str | None = None


class EnrichedMessage(BaseModel):
    """Enrichment 단계(뉴스 본문·vision·티커)를 거친 메시지."""

    raw: RawMessage
    article_bodies: list[ArticleBody] = Field(default_factory=list)
    image_description: str | None = None
    tickers: list[Ticker] = Field(default_factory=list)

    @property
    def combined_text(self) -> str:
        """임베딩·LLM 입력용 통합 텍스트."""
        parts = [self.raw.text]
        if self.image_description:
            parts.append(f"[이미지] {self.image_description}")
        for art in self.article_bodies:
            if art.title:
                parts.append(f"[기사] {art.title}")
            if art.body:
                parts.append(art.body)
        return "\n".join(p for p in parts if p).strip()


class SourceRef(BaseModel):
    """t.me 링크 복원용 최소 참조."""

    channel_username: str
    message_id: int

    @property
    def url(self) -> str:
        return f"https://t.me/{self.channel_username}/{self.message_id}"


class PreCluster(BaseModel):
    """임베딩 기반 사전 클러스터(LLM 호출 전)."""

    representative: EnrichedMessage
    members: list[EnrichedMessage]

    @property
    def all_sources(self) -> list[SourceRef]:
        """채널별 첫 등장 멤버 1개만 남겨 시각적 노이즈 제거."""
        seen: set[str] = set()
        out: list[SourceRef] = []
        for m in self.members:
            ch = m.raw.channel_username
            if ch in seen:
                continue
            seen.add(ch)
            out.append(SourceRef(channel_username=ch, message_id=m.raw.message_id))
        return out


class ClusteredTopic(BaseModel):
    """LLM이 통합·요약한 최종 토픽."""

    title: str
    summary: str
    importance: Importance = "medium"
    sources: list[SourceRef] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)


class StockQuote(BaseModel):
    """FinanceDataReader에서 조회한 시세."""

    code: str
    name: str | None = None
    exchange: str | None = None  # "KOSPI", "KOSDAQ", "NYSE" 등
    price: float
    change_pct: float | None = None
    currency: Literal["KRW", "USD"]
    as_of: date


class OutboundBlock(BaseModel):
    """Telegram 전송을 위한 최종 블록(토픽 + 시세)."""

    topic: ClusteredTopic
    quotes: list[StockQuote] = Field(default_factory=list)
