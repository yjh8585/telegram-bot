"""SQLite 기반 상태·캐시 저장소."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS last_seen (
        channel_username TEXT PRIMARY KEY,
        message_id INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS url_cache (
        url_hash TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT,
        body TEXT,
        fetched_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_cache (
        image_sha1 TEXT PRIMARY KEY,
        description TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sent_hash (
        content_hash TEXT PRIMARY KEY,
        sent_at TEXT NOT NULL
    )
    """,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateRepository:
    """SQLite로 채널 상태·URL/이미지 캐시·전송 이력 관리."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        for stmt in _SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- last_seen -------------------------------------------------
    def get_last_seen(self, channel: str) -> int | None:
        row = self._conn.execute(
            "SELECT message_id FROM last_seen WHERE channel_username = ?", (channel,)
        ).fetchone()
        return int(row["message_id"]) if row else None

    def set_last_seen(self, channel: str, message_id: int) -> None:
        self._conn.execute(
            """
            INSERT INTO last_seen(channel_username, message_id) VALUES (?, ?)
            ON CONFLICT(channel_username) DO UPDATE SET
                message_id = MAX(excluded.message_id, last_seen.message_id)
            """,
            (channel, message_id),
        )
        self._conn.commit()

    # --- url cache -------------------------------------------------
    def get_url_cache(self, url_hash: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT url, title, body, fetched_at FROM url_cache WHERE url_hash = ?",
            (url_hash,),
        ).fetchone()
        return dict(row) if row else None

    def set_url_cache(self, url_hash: str, url: str, title: str, body: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO url_cache(url_hash, url, title, body, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url_hash, url, title, body, _now_iso()),
        )
        self._conn.commit()

    # --- image cache -----------------------------------------------
    def get_image_cache(self, sha1: str) -> str | None:
        row = self._conn.execute(
            "SELECT description FROM image_cache WHERE image_sha1 = ?", (sha1,)
        ).fetchone()
        return row["description"] if row else None

    def set_image_cache(self, sha1: str, description: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO image_cache(image_sha1, description, created_at)
            VALUES (?, ?, ?)
            """,
            (sha1, description, _now_iso()),
        )
        self._conn.commit()

    # --- sent_hash -------------------------------------------------
    def was_sent(self, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sent_hash WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row is not None

    def mark_sent(self, content_hash: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_hash(content_hash, sent_at) VALUES (?, ?)",
            (content_hash, _now_iso()),
        )
        self._conn.commit()
