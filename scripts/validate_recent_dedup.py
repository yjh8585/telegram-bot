"""배포 전 검증: 최근 48h 실제 데이터에 cross-run 중복 필터를 적용해 제거 목록을 출력.

24h 이전 메시지를 '최근 발송 기억'으로, 24h 이내를 '새 수집'으로 간주해
여러 임계값에서 제거 건수와 매칭 근거를 보여준다. Anthropic API 비용 없음.

사용: python -m scripts.validate_recent_dedup
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

import numpy as np
from anthropic import Anthropic
from sentence_transformers import SentenceTransformer

from src.config import CHANNELS, Settings, get_settings
from src.dtos import RawMessage
from src.repositories.telethon_repo import TelethonRepository
from src.services.message_filter import filter_messages
from src.services.pre_cluster import DEFAULT_MODEL_NAME
from src.services.recent_dedup import _strip_urls
from src.services.ticker_dict import TickerDict
from src.services.ticker_extractor import TickerExtractor

_LOOKBACK_H = 48
_SPLIT_H = 24
_THRESHOLDS = (0.80, 0.85, 0.90)
_DETAIL_TH = 0.85
_SNIPPET = 60


async def _fetch(settings: Settings) -> list[RawMessage]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=_LOOKBACK_H)
    msgs: list[RawMessage] = []
    async with TelethonRepository(
        settings.tg_api_id, settings.tg_api_hash, settings.tg_session_string
    ) as tg:
        for ch in CHANNELS:
            got = await tg.fetch_window(ch, since, now, min_id=0)
            msgs.extend(got)
    return msgs


def _snip(text: str) -> str:
    return (text or "").replace("\n", " ")[:_SNIPPET]


def _report(memory: list[RawMessage], new: list[RawMessage], model: SentenceTransformer) -> None:
    # recent_dedup과 동일하게 URL을 제거하고, 본문이 빈(링크만) 항목은 비교에서 제외.
    mem_pairs = [(m, t) for m in memory if (t := _strip_urls(m.text or ""))]
    new_pairs = [(m, t) for m in new if (t := _strip_urls(m.text or ""))]
    print(f"URL 제거·빈 본문 제외 후 비교 대상: memory {len(mem_pairs)}건 / new {len(new_pairs)}건")
    if not mem_pairs or not new_pairs:
        print("⚠ 한쪽이 비어 비교 불가.")
        return
    mem_emb = model.encode(
        [t for _, t in mem_pairs], normalize_embeddings=True, convert_to_numpy=True
    )
    new_emb = model.encode(
        [t for _, t in new_pairs], normalize_embeddings=True, convert_to_numpy=True
    )
    sim = new_emb @ mem_emb.T
    best = sim.max(axis=1)
    best_j = sim.argmax(axis=1)
    for th in _THRESHOLDS:
        drops = int((best >= th).sum())
        print(f"\n=== threshold {th:.2f}: new {len(new_pairs)}건 중 {drops}건 제거 ===")
        if abs(th - _DETAIL_TH) < 1e-9:
            for i in range(len(new_pairs)):
                if best[i] >= th:
                    print(
                        f"  drop sim={best[i]:.3f}\n"
                        f"    new : {_snip(new_pairs[i][0].text)}\n"
                        f"    ↔mem: {_snip(mem_pairs[int(best_j[i])][0].text)}"
                    )


async def _main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    msgs = await _fetch(settings)
    client = Anthropic(api_key=settings.anthropic_api_key)
    tdict = TickerDict(settings.state_db_path.parent)
    tex = TickerExtractor(tdict, client, settings.model)
    msgs = filter_messages(msgs, tex)
    cutoff = datetime.now(UTC) - timedelta(hours=_SPLIT_H)
    memory = [m for m in msgs if m.posted_at < cutoff]
    new = [m for m in msgs if m.posted_at >= cutoff]
    print(f"필터 후 {len(msgs)}건 → memory(≥24h前) {len(memory)}건 / new(24h内) {len(new)}건")
    model = SentenceTransformer(DEFAULT_MODEL_NAME)
    _report(memory, new, model)


if __name__ == "__main__":
    asyncio.run(_main())
