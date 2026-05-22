"""loguru 기반 로거 + 민감정보 마스킹 패처."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

# 토큰·api_hash·Claude 키·긴 base64(세션 문자열)를 로그에서 마스킹
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}"),  # bot token
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"\b[a-f0-9]{32}\b"),  # api_hash 패턴
    re.compile(r"[A-Za-z0-9+/=]{120,}"),  # 긴 base64 (session string)
)
_MASK = "***MASKED***"
_CONFIGURED = False


def _mask_sensitive(record: Record) -> None:
    """record['message']에 포함된 민감 문자열을 마스킹한다."""
    msg = record["message"]
    for pattern in _SENSITIVE_PATTERNS:
        msg = pattern.sub(_MASK, msg)
    record["message"] = msg


def setup_logger() -> Any:
    """로거 초기화(1회). 반환값은 loguru.logger 그대로."""
    global _CONFIGURED
    if _CONFIGURED:
        return logger
    logger.remove()
    logger.configure(patcher=_mask_sensitive)
    logger.add(
        sys.stdout,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}:{line}</cyan> {message}"
        ),
    )
    _CONFIGURED = True
    return logger


def log_api_usage(name: str, response: Any) -> None:
    """Claude API 응답의 usage 토큰 4종을 한 줄로 INFO 로그.

    회차당 누적 토큰을 1~2주 모아서 캐시 적용·입력 컷오프 등 비용 의사결정에 사용.
    SDK 응답 형태가 바뀌어도 로깅 실패가 본 흐름을 막지 않도록 광범위 캐치.
    """
    try:
        u = getattr(response, "usage", None)
        if u is None:
            return
        logger.info(
            f"usage[{name}] in={getattr(u, 'input_tokens', 0)} "
            f"out={getattr(u, 'output_tokens', 0)} "
            f"cache_r={getattr(u, 'cache_read_input_tokens', 0) or 0} "
            f"cache_w={getattr(u, 'cache_creation_input_tokens', 0) or 0}"
        )
    except Exception as e:
        logger.debug(f"usage 로깅 실패 name={name} err={e}")
