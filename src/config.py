"""환경변수·상수 로더."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 (src/config.py → parent.parent)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 수집 대상 채널 (t.me/<username> 기준).
# 코인 채널(seaotterbtc, darthacking)·비활성 채널(desperatestudycafe) 제외 → 4개.
CHANNELS: tuple[str, ...] = (
    "FastStockNews",
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
