"""StateRepository CRUD 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.repositories.state_repo import StateRepository


def test_last_seen_roundtrip(tmp_path: Path) -> None:
    repo = StateRepository(tmp_path / "s.db")
    try:
        assert repo.get_last_seen("FastStockNews") is None
        repo.set_last_seen("FastStockNews", 100)
        assert repo.get_last_seen("FastStockNews") == 100
    finally:
        repo.close()


def test_last_seen_only_advances(tmp_path: Path) -> None:
    """낮은 message_id로 set해도 기존 값은 유지(최댓값만 보존)."""
    repo = StateRepository(tmp_path / "s.db")
    try:
        repo.set_last_seen("ch", 100)
        repo.set_last_seen("ch", 50)
        assert repo.get_last_seen("ch") == 100
        repo.set_last_seen("ch", 200)
        assert repo.get_last_seen("ch") == 200
    finally:
        repo.close()


def test_url_cache_crud(tmp_path: Path) -> None:
    repo = StateRepository(tmp_path / "s.db")
    try:
        assert repo.get_url_cache("hash1") is None
        repo.set_url_cache("hash1", "https://ex.com", "제목", "본문")
        cached = repo.get_url_cache("hash1")
        assert cached is not None
        assert cached["title"] == "제목"
        assert cached["body"] == "본문"
        # 동일 키로 REPLACE
        repo.set_url_cache("hash1", "https://ex.com", "새제목", "새본문")
        assert (repo.get_url_cache("hash1") or {})["title"] == "새제목"
    finally:
        repo.close()


def test_image_cache_crud(tmp_path: Path) -> None:
    repo = StateRepository(tmp_path / "s.db")
    try:
        assert repo.get_image_cache("sha1-a") is None
        repo.set_image_cache("sha1-a", "차트 설명")
        assert repo.get_image_cache("sha1-a") == "차트 설명"
    finally:
        repo.close()


def test_recent_topics_window(tmp_path: Path) -> None:
    """since 이후 텍스트만 조회된다."""
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
        repo.add_recent_topics(["삼성전자 실적", "환율 급등"], t0)
        got = repo.get_recent_topic_texts(t0 - timedelta(hours=1))
        assert set(got) == {"삼성전자 실적", "환율 급등"}
        # since가 저장 시각보다 뒤면 0건(창 밖)
        assert repo.get_recent_topic_texts(t0 + timedelta(hours=1)) == []
    finally:
        repo.close()


def test_recent_topics_prune(tmp_path: Path) -> None:
    """before보다 오래된 행은 삭제된다."""
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
        repo.add_recent_topics(["old"], t0)
        repo.add_recent_topics(["new"], t0 + timedelta(hours=25))
        repo.prune_recent_topics(t0 + timedelta(hours=24))
        assert repo.get_recent_topic_texts(t0 - timedelta(days=1)) == ["new"]
    finally:
        repo.close()


def test_persistence_across_instances(tmp_path: Path) -> None:
    """같은 파일을 재오픈했을 때 값이 유지되는지."""
    db = tmp_path / "s.db"
    r1 = StateRepository(db)
    r1.set_last_seen("ch", 42)
    r1.close()

    r2 = StateRepository(db)
    try:
        assert r2.get_last_seen("ch") == 42
    finally:
        r2.close()
