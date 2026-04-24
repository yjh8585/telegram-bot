"""이미지 → Claude vision 한국어 설명. sha1 기반 캐시로 재호출 방지."""
from __future__ import annotations

import base64
from typing import Any

from anthropic import Anthropic
from loguru import logger

from src.repositories.state_repo import StateRepository

_VISION_PROMPT = (
    "이 이미지의 핵심 내용을 3줄 이내 한국어로 요약하세요. "
    "차트·표·캡처·뉴스 스크린샷이면 거기 담긴 숫자·종목명·날짜를 구체적으로 포함하세요. "
    "특별한 금융 정보가 없다면 간단히 '의미 있는 금융 정보 없음'이라고만 답하세요."
)
_MAX_TOKENS = 500


def _detect_media_type(data: bytes) -> str:
    """바이너리 시그니처로 이미지 타입 판별. 모르면 JPEG 가정."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _extract_text(msg: Any) -> str:
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


class VisionService:
    """Claude vision 래퍼. StateRepository의 image_cache로 중복 호출 차단."""

    def __init__(self, client: Anthropic, model: str, state: StateRepository) -> None:
        self._client = client
        self._model = model
        self._state = state

    def describe(self, image_sha1: str, image_bytes: bytes) -> str | None:
        cached = self._state.get_image_cache(image_sha1)
        if cached is not None:
            return cached
        return self._describe_fresh(image_sha1, image_bytes)

    def _describe_fresh(self, image_sha1: str, image_bytes: bytes) -> str | None:
        media_type = _detect_media_type(image_bytes)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": _VISION_PROMPT},
                        ],
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"vision 호출 실패 sha1={image_sha1[:8]}.. err={e}")
            return None

        description = _extract_text(response)
        if description:
            self._state.set_image_cache(image_sha1, description)
        return description
