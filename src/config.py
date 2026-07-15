"""환경변수·상수 로더."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 (src/config.py → parent.parent)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 수집 대상 채널 (t.me/<username> 기준).
# 코인 채널(seaotterbtc, darthacking)·비활성 채널(desperatestudycafe) 제외.
# FastStockNews는 투자뉴스 범위가 너무 넓어 개인 관심사와 맞지 않아 제외(2026-07-15).
CHANNELS: tuple[str, ...] = (
    "Yeouido_Lab",
    "TNBfolio",
    "triple_stock",
)


class Settings(BaseSettings):
    """`.env` + OS 환경변수에서 값을 읽는 설정. 모든 필수값이 없으면 런타임 에러."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telethon user session
    tg_api_id: int
    tg_api_hash: str
    tg_session_string: str = ""

    # Telegram Bot API
    bot_token: str = ""
    bot_chat_id: int = 0

    # Anthropic
    anthropic_api_key: str
    model: str = "claude-haiku-4-5-20251001"

    # 클러스터링·동작
    dedupe_threshold: float = 0.82
    recent_dedup_threshold: float = 0.90
    recent_dedup_window_hours: int = 24

    # 비용 절감: 정규식·KRX 사전·코인 키워드로 못 찾은 종목을 Claude로 재추출하는
    # LLM 폴백. 호출 회피(비용↓)를 위해 기본 비활성화. env로 되돌리기 가능.
    enable_ticker_llm_fallback: bool = False

    # 비용 절감: 유사 이미지(perceptual hash) 캐시. 기본 shadow(호출 유지·로그만) —
    # Actions 로그로 오탐 없음 확인 후 True로 켠다. distance는 phash Hamming(0~64).
    enable_image_phash_cache: bool = False
    image_phash_max_distance: int = 4

    # 비용 절감: summarize 입력(클러스터 대표 본문 컷오프)·출력 토픽 상한.
    # max_topics=0은 무제한(끔). >0이면 멤버수(신호 강도) 상위 N개만 요약.
    summarize_rep_text_limit: int = 1600
    summarize_max_topics: int = 0

    # 경로
    tz: str = "Asia/Seoul"
    state_db_path: Path = Field(default=PROJECT_ROOT / "state" / "state.db")


_settings: Settings | None = None


def get_settings() -> Settings:
    """프로세스당 1회 로드되는 설정 싱글턴."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
