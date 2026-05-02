"""KRX 종목명 ↔ 6자리 코드 사전. FinanceDataReader 기반, 하루 1회 갱신."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import FinanceDataReader as fdr
from loguru import logger

_CACHE_FILENAME = "krx_ticker_dict.json"


class TickerDict:
    """KRX 상장 종목명 ↔ 코드 lookup. exchange 정보 포함. 디스크 캐시(하루 단위)."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_path = cache_dir / _CACHE_FILENAME
        self._code_to_name: dict[str, str] = {}
        self._name_to_code: dict[str, str] = {}
        self._code_to_exchange: dict[str, str] = {}
        self._load_or_refresh()

    def name_of(self, code: str) -> str | None:
        return self._code_to_name.get(code)

    def code_of(self, name: str) -> str | None:
        return self._name_to_code.get(name)

    def exchange_of(self, code: str) -> str | None:
        """KOSPI / KOSDAQ 등 거래소 코드 반환."""
        return self._code_to_exchange.get(code) or None

    def names(self) -> list[str]:
        return list(self._name_to_code.keys())

    def _load_or_refresh(self) -> None:
        if self._try_load_fresh_cache():
            return
        # FDR 갱신 실패 대비 이전 캐시를 먼저 로드 (폴백)
        self._try_load_stale_cache()
        self._refresh_from_fdr()

    def _try_load_stale_cache(self) -> bool:
        """날짜 무관 이전 캐시 로드 (FDR 갱신 실패 시 폴백용)."""
        if not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        self._code_to_name = dict(data.get("code_to_name", {}))
        self._name_to_code = dict(data.get("name_to_code", {}))
        self._code_to_exchange = dict(data.get("code_to_exchange", {}))
        if self._code_to_name:
            logger.info(f"이전 캐시 폴백 로드: {len(self._code_to_name)}건 (as_of={data.get('as_of')})")
        return bool(self._code_to_name)

    def _try_load_fresh_cache(self) -> bool:
        if not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if data.get("as_of") != date.today().isoformat():
            return False
        self._code_to_name = dict(data.get("code_to_name", {}))
        self._name_to_code = dict(data.get("name_to_code", {}))
        self._code_to_exchange = dict(data.get("code_to_exchange", {}))
        return bool(self._code_to_name)

    def _refresh_from_fdr(self) -> None:
        logger.info("KRX 종목 사전 갱신 중 (FinanceDataReader)")
        try:
            df = fdr.StockListing("KRX")
            code_col = "Code" if "Code" in df.columns else "Symbol"
            market_col = "Market" if "Market" in df.columns else None
            for _, row in df.iterrows():
                code = str(row[code_col]).zfill(6)
                name = str(row["Name"]).strip()
                if not name or not code or name == code:
                    continue
                self._code_to_name[code] = name
                self._name_to_code[name] = code
                if market_col:
                    exchange = str(row[market_col]).strip()
                    if exchange:
                        self._code_to_exchange[code] = exchange
            self._save_cache()
            logger.info(f"KRX 사전 {len(self._code_to_name)}건 로드")
        except Exception as e:
            logger.warning(f"KRX 사전 갱신 실패: {e} — 종목명 조회 불가로 진행")

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "as_of": date.today().isoformat(),
            "code_to_name": self._code_to_name,
            "name_to_code": self._name_to_code,
            "code_to_exchange": self._code_to_exchange,
        }
        self._cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
