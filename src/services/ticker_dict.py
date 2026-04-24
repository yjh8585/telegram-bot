"""KRX 종목명 ↔ 6자리 코드 사전. FinanceDataReader 기반, 하루 1회 갱신."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import FinanceDataReader as fdr
from loguru import logger

_CACHE_FILENAME = "krx_ticker_dict.json"


class TickerDict:
    """KRX 상장 종목명 ↔ 코드 lookup. 디스크 캐시(하루 단위)."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_path = cache_dir / _CACHE_FILENAME
        self._code_to_name: dict[str, str] = {}
        self._name_to_code: dict[str, str] = {}
        self._load_or_refresh()

    def name_of(self, code: str) -> str | None:
        return self._code_to_name.get(code)

    def code_of(self, name: str) -> str | None:
        return self._name_to_code.get(name)

    def names(self) -> list[str]:
        return list(self._name_to_code.keys())

    def _load_or_refresh(self) -> None:
        if self._try_load_fresh_cache():
            return
        self._refresh_from_fdr()

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
        return bool(self._code_to_name)

    def _refresh_from_fdr(self) -> None:
        logger.info("KRX 종목 사전 갱신 중 (FinanceDataReader)")
        df = fdr.StockListing("KRX")
        code_col = "Code" if "Code" in df.columns else "Symbol"
        for _, row in df.iterrows():
            code = str(row[code_col]).zfill(6)
            name = str(row["Name"]).strip()
            if not name or not code:
                continue
            self._code_to_name[code] = name
            self._name_to_code[name] = code
        self._save_cache()
        logger.info(f"KRX 사전 {len(self._code_to_name)}건 로드")

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "as_of": date.today().isoformat(),
            "code_to_name": self._code_to_name,
            "name_to_code": self._name_to_code,
        }
        self._cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
