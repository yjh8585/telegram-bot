"""ArticleFetcher: URL 캐시 히트/미스 동작 검증."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.repositories.state_repo import StateRepository
from src.services.article_fetcher import ArticleFetcher


def test_cache_hit_skips_network(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "s.db")
    fetcher = ArticleFetcher(state)

    with patch("src.services.article_fetcher.trafilatura.fetch_url") as fetch_url, patch(
        "src.services.article_fetcher.trafilatura.extract"
    ) as extract:
        fetch_url.return_value = "<html>...</html>"
        extract.return_value = '{"title": "제목", "text": "본문"}'

        first = fetcher.fetch("https://example.com/article-1")
        assert first is not None
        assert first.title == "제목"
        assert fetch_url.call_count == 1

        # 두 번째 호출은 캐시 히트 → fetch_url 호출되지 않아야 한다
        second = fetcher.fetch("https://example.com/article-1")
        assert second is not None
        assert second.title == "제목"
        assert fetch_url.call_count == 1

    state.close()


def test_fetch_failure_returns_none(tmp_path: Path) -> None:
    state = StateRepository(tmp_path / "s.db")
    fetcher = ArticleFetcher(state)

    with patch("src.services.article_fetcher.trafilatura.fetch_url") as fetch_url:
        fetch_url.return_value = None
        result = fetcher.fetch("https://example.com/404")
        assert result is None

    state.close()


def test_url_fragment_is_normalized(tmp_path: Path) -> None:
    """동일 페이지의 #fragment만 다른 URL은 같은 캐시 키로 매칭되어야 한다."""
    state = StateRepository(tmp_path / "s.db")
    fetcher = ArticleFetcher(state)

    with patch("src.services.article_fetcher.trafilatura.fetch_url") as fetch_url, patch(
        "src.services.article_fetcher.trafilatura.extract"
    ) as extract:
        fetch_url.return_value = "<html/>"
        extract.return_value = '{"title": "t", "text": "b"}'

        fetcher.fetch("https://example.com/a")
        fetcher.fetch("https://example.com/a#section-2")
        assert fetch_url.call_count == 1

    state.close()
