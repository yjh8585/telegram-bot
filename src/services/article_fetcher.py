"""뉴스 URL 본문 추출 + SQLite URL 캐시."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urldefrag

import trafilatura
from loguru import logger

from src.dtos import ArticleBody
from src.repositories.state_repo import StateRepository

_BODY_MAX_CHARS = 4000  # 토큰 절감용 본문 컷오프


def _url_hash(url: str) -> str:
    cleaned, _ = urldefrag(url)
    return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()


def _trim(text: str, limit: int = _BODY_MAX_CHARS) -> str:
    return text[:limit] if len(text) > limit else text


class ArticleFetcher:
    """URL을 trafilatura로 본문 추출. 동일 URL은 SQLite 캐시에서 재사용."""

    def __init__(self, state: StateRepository) -> None:
        self._state = state

    def fetch(self, url: str) -> ArticleBody | None:
        h = _url_hash(url)
        cached = self._state.get_url_cache(h)
        if cached is not None:
            return ArticleBody(
                url=url,
                title=cached.get("title") or "",
                body=cached.get("body") or "",
            )
        return self._fetch_fresh(url, h)

    def _fetch_fresh(self, url: str, url_hash: str) -> ArticleBody | None:
        try:
            html = trafilatura.fetch_url(url, no_ssl=True)
            if not html:
                return None
            extracted = trafilatura.extract(
                html,
                output_format="json",
                include_comments=False,
                with_metadata=True,
            )
            if not extracted:
                return None
            data = json.loads(extracted)
        except Exception as e:  # 외부 호출이므로 포괄 캐치 허용
            logger.warning(f"article_fetch 실패 url={url} err={e}")
            return None

        title = _trim(str(data.get("title") or ""), 200)
        body = _trim(str(data.get("text") or ""))
        self._state.set_url_cache(url_hash, url, title, body)
        return ArticleBody(url=url, title=title, body=body)
