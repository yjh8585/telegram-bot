"""이미지 → Claude vision 한국어 설명. sha1·유사(phash) 캐시 + 다운샘플로 비용 절감."""

from __future__ import annotations

import base64
import io
from typing import Any

import imagehash
from anthropic import Anthropic
from loguru import logger
from PIL import Image

from src.logger import log_api_usage
from src.repositories.state_repo import StateRepository

# dedupe_summarizer에서 이미지 필터 기준으로도 사용하는 공유 상수
NO_INFO_MARKER = "의미 있는 금융 정보 없음"

_VISION_PROMPT = (
    "이 이미지의 핵심 내용을 3줄 이내 한국어로 요약하세요. "
    "차트·표·캡처·뉴스 스크린샷이면 거기 담긴 숫자·종목명·날짜를 구체적으로 포함하세요. "
    f"특별한 금융 정보가 없다면 간단히 '{NO_INFO_MARKER}'이라고만 답하세요."
)
_MAX_TOKENS = 200  # 3줄 한국어 요약 기준 충분
_MAX_IMAGE_EDGE = 1024  # vision 전송 전 장변 상한(이미지 토큰 절감). 3줄 요약엔 충분.
_JPEG_QUALITY = 85
_PHASH_SCAN_LIMIT = 500  # 유사 매칭 시 비교할 최근 캐시 행 수(로컬 스캔)


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


def _downsample(img: Image.Image) -> bytes:
    """장변 _MAX_IMAGE_EDGE로 축소 후 JPEG 재인코딩한 바이트."""
    rgb = img.convert("RGB")
    rgb.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def _prepare(image_bytes: bytes) -> tuple[bytes, str, str | None]:
    """1회 디코드 → (전송 바이트, media_type, phash hex). 디코드 실패 시 원본 그대로."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        phash = str(imagehash.phash(img))
    except Exception as e:
        logger.debug(f"이미지 디코드 실패, 원본 전송: {e}")
        return image_bytes, _detect_media_type(image_bytes), None
    if max(img.size) <= _MAX_IMAGE_EDGE:
        return image_bytes, _detect_media_type(image_bytes), phash
    return _downsample(img), "image/jpeg", phash


def _nearest_phash(
    target: str, candidates: list[tuple[str, str]], max_distance: int
) -> tuple[str, int] | None:
    """target과 Hamming 거리 max_distance 이하인 최근접 후보 (description, dist) 반환."""
    try:
        t = imagehash.hex_to_hash(target)
    except Exception:
        return None
    best: tuple[str, int] | None = None
    for ph, desc in candidates:
        try:
            dist = int(t - imagehash.hex_to_hash(ph))
        except Exception:
            continue
        if dist <= max_distance and (best is None or dist < best[1]):
            best = (desc, dist)
    return best


class VisionService:
    """Claude vision 래퍼. sha1 정확 캐시 + phash 유사 캐시로 중복 호출 차단."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        state: StateRepository,
        enable_phash_cache: bool = False,
        phash_max_distance: int = 4,
    ) -> None:
        self._client = client
        self._model = model
        self._state = state
        self._enable_phash_cache = enable_phash_cache
        self._phash_max_distance = phash_max_distance

    def describe(self, image_sha1: str, image_bytes: bytes) -> str | None:
        cached = self._state.get_image_cache(image_sha1)
        if cached is not None:
            return cached
        return self._describe_fresh(image_sha1, image_bytes)

    def _match_phash(self, phash: str) -> str | None:
        """유사 이미지 설명 재사용(활성 시) 또는 shadow 로그(기본). 없으면 None."""
        hit = _nearest_phash(
            phash, self._state.get_image_phashes(_PHASH_SCAN_LIMIT), self._phash_max_distance
        )
        if hit is None:
            return None
        desc, dist = hit
        snippet = desc[:40].replace("\n", " ")
        if self._enable_phash_cache:
            logger.info(f"[vision] phash 재사용 dist={dist} | {snippet}")
            return desc
        logger.info(f"[vision] phash 유사(shadow, 호출유지) dist={dist} | {snippet}")
        return None

    def _describe_fresh(self, image_sha1: str, image_bytes: bytes) -> str | None:
        send_bytes, media_type, phash = _prepare(image_bytes)
        if phash is not None:
            reused = self._match_phash(phash)
            if reused is not None:
                self._state.set_image_cache(image_sha1, reused, phash)
                return reused
        b64 = base64.b64encode(send_bytes).decode("ascii")
        user_content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": _VISION_PROMPT},
        ]
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": user_content}],  # type: ignore[typeddict-item]
            )
        except Exception as e:
            logger.warning(f"vision 호출 실패 sha1={image_sha1[:8]}.. err={e}")
            return None

        log_api_usage("vision", response)
        description = _extract_text(response)
        if description:
            self._state.set_image_cache(image_sha1, description, phash)
        return description
