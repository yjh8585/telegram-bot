"""Telethon(MTProto user session) 기반 채널 메시지 수집 저장소."""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
from datetime import datetime
from types import TracebackType
from typing import Self

from loguru import logger
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from src.dtos import RawMessage

_MAX_FLOOD_WAIT_SECONDS = 60
_URL_RE = re.compile(r"https?://[^\s)>\]]+")


class TelethonRepository:
    """채널에서 window 내 메시지를 DTO로 반환. async 컨텍스트 매니저로 사용."""

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._client = TelegramClient(StringSession(session_string), api_id, api_hash)

    async def __aenter__(self) -> Self:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("Telethon 세션이 만료되었습니다. scripts/login.py 재실행 필요.")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.disconnect()

    async def fetch_window(
        self, channel: str, since_utc: datetime, until_utc: datetime
    ) -> list[RawMessage]:
        """since ≤ posted_at < until 메시지를 반환. FloodWait는 짧으면 대기, 길면 스킵."""
        try:
            return await self._iter_window(channel, since_utc, until_utc)
        except FloodWaitError as e:
            if e.seconds > _MAX_FLOOD_WAIT_SECONDS:
                logger.warning(f"[{channel}] FloodWait {e.seconds}s → 스킵")
                return []
            logger.info(f"[{channel}] FloodWait {e.seconds}s 대기 후 재시도")
            await asyncio.sleep(e.seconds + 1)
            return await self._iter_window(channel, since_utc, until_utc)

    async def _iter_window(
        self, channel: str, since_utc: datetime, until_utc: datetime
    ) -> list[RawMessage]:
        results: list[RawMessage] = []
        # offset_date=until → 이 시각 이전 메시지부터 최신→과거 순회
        async for msg in self._client.iter_messages(channel, offset_date=until_utc):
            msg_date: datetime = msg.date
            if msg_date < since_utc:
                break
            if msg_date >= until_utc:
                continue
            results.append(await self._to_dto(channel, msg))
        return results

    async def _to_dto(self, channel: str, msg: Message) -> RawMessage:
        photo_sha1, photo_bytes = await self._download_photo(msg)
        urls = self._extract_urls(msg)
        return RawMessage(
            channel_username=channel,
            message_id=msg.id,
            posted_at=msg.date,
            text=msg.message or "",
            photo_sha1=photo_sha1,
            photo_caption=(msg.message or None) if photo_sha1 else None,
            photo_bytes=photo_bytes,
            urls=urls,
        )

    async def _download_photo(self, msg: Message) -> tuple[str | None, bytes | None]:
        """사진을 메모리에 받아 (sha1, bytes)를 반환. 사진이 없으면 (None, None)."""
        if not msg.photo:
            return None, None
        buffer = io.BytesIO()
        await msg.download_media(file=buffer)
        data = buffer.getvalue()
        return hashlib.sha1(data).hexdigest(), data

    @staticmethod
    def _extract_urls(msg: Message) -> list[str]:
        """web_preview 링크 + 본문 regex로 URL 수집(순서 유지 dedupe)."""
        urls: list[str] = []
        wp = getattr(msg, "web_preview", None)
        if wp is not None and getattr(wp, "url", None):
            urls.append(wp.url)
        if msg.message:
            urls.extend(_URL_RE.findall(msg.message))
        seen: set[str] = set()
        deduped: list[str] = []
        for u in urls:
            if u not in seen:
                deduped.append(u)
                seen.add(u)
        return deduped
