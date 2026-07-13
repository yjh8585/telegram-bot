# 실행 간(cross-run) 의미 중복 필터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최근 발송한 토픽과 의미가 유사한 새 메시지를 요약 전에 제거해, vision·요약 API 비용을 줄이고 실행/날짜를 넘는 반복을 없앤다.

**Architecture:** 저가치 필터 직후·enrichment 전에 새 서비스 `RecentDedupService`를 삽입한다. 발송한 토픽의 `제목+요약`을 SQLite `recent_topics` 테이블에 저장하고, 다음 런에서 새 메시지 원본 텍스트를 임베딩해 최근 토픽과 cosine 유사도가 임계값 이상이면 제거한다. 임베딩 모델(MiniLM)은 `pre_cluster`와 공유해 이중 로드를 막는다.

**Tech Stack:** Python 3.12, pydantic v2, sentence-transformers(paraphrase-multilingual-MiniLM-L12-v2), numpy, SQLite, loguru, pytest.

**설계 문서:** `docs/specs/2026-07-13-cross-run-dedup-design.md`

**⚠ 롤아웃 순서:** Task 1~5(부품·검증 스크립트)를 먼저 완료 → **Task 6(오프라인 검증)에서 사용자 승인** → 그 후에만 Task 7(main.py 배선). 검증 없이 배선 금지.

---

## 파일 구조

- **수정** `src/repositories/state_repo.py` — `sent_hash` 제거, `recent_topics` 테이블·CRUD 추가.
- **수정** `tests/test_state_repo.py` — `test_sent_hash` 제거, `recent_topics` 테스트 추가.
- **수정** `src/services/pre_cluster.py` — 생성자에 모델 주입(선택 인자).
- **생성** `src/services/recent_dedup.py` — cross-run 중복 필터 서비스.
- **생성** `tests/test_recent_dedup.py` — 순수 함수 + 서비스 단위 테스트.
- **수정** `src/config.py` — `recent_dedup_threshold`·`recent_dedup_window_hours` 추가.
- **생성** `scripts/validate_recent_dedup.py` — 배포 전 오프라인 검증 도구.
- **수정** `src/main.py` — 파이프라인 배선 + 발송분 기록.
- **수정** `USER_ACTIONS.md` — 검증 실행 절차 추가.

---

### Task 1: state_repo — `recent_topics` 추가 및 `sent_hash` 제거

**Files:**
- Modify: `src/repositories/state_repo.py`
- Test: `tests/test_state_repo.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_state_repo.py`의 `test_sent_hash`(59~69행)를 삭제하고, 파일 상단 import에 `from datetime import UTC, datetime, timedelta`를 추가한 뒤 아래 두 테스트를 추가한다.

```python
def test_recent_topics_window(tmp_path: Path) -> None:
    """since 이후 텍스트만 조회된다."""
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
        repo.add_recent_topics(["삼성전자 실적", "환율 급등"], t0)
        got = repo.get_recent_topic_texts(t0 - timedelta(hours=1))
        assert set(got) == {"삼성전자 실적", "환율 급등"}
        # since가 저장 시각보다 뒤면 0건(창 밖)
        assert repo.get_recent_topic_texts(t0 + timedelta(hours=1)) == []
    finally:
        repo.close()


def test_recent_topics_prune(tmp_path: Path) -> None:
    """before보다 오래된 행은 삭제된다."""
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
        repo.add_recent_topics(["old"], t0)
        repo.add_recent_topics(["new"], t0 + timedelta(hours=25))
        repo.prune_recent_topics(t0 + timedelta(hours=24))
        assert repo.get_recent_topic_texts(t0 - timedelta(days=1)) == ["new"]
    finally:
        repo.close()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_state_repo.py -v`
Expected: FAIL — `AttributeError: 'StateRepository' object has no attribute 'add_recent_topics'`

- [ ] **Step 3: state_repo 구현** — `_SCHEMA` 튜플에서 `sent_hash` DDL(33~38행)을 제거하고 아래 `recent_topics` DDL로 교체한다.

```python
    """
    CREATE TABLE IF NOT EXISTS recent_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
```

그리고 `was_sent`/`mark_sent` 메서드(113~125행)를 삭제하고 아래를 추가한다. 파일 상단 import에 `from datetime import UTC, datetime`이 이미 있으면 `datetime`만 사용, 없으면 `datetime`을 추가한다(현재 파일은 `from datetime import UTC, datetime`을 이미 import 중).

```python
    # --- recent_topics ---------------------------------------------
    def get_recent_topic_texts(self, since: datetime) -> list[str]:
        """created_at >= since 인 발송 토픽 텍스트를 id 순으로 반환."""
        rows = self._conn.execute(
            "SELECT text FROM recent_topics WHERE created_at >= ? ORDER BY id",
            (since.isoformat(),),
        ).fetchall()
        return [row["text"] for row in rows]

    def add_recent_topics(self, texts: list[str], now: datetime) -> None:
        """발송 토픽 텍스트들을 현재 시각으로 기록."""
        ts = now.isoformat()
        self._conn.executemany(
            "INSERT INTO recent_topics(text, created_at) VALUES (?, ?)",
            [(t, ts) for t in texts],
        )
        self._conn.commit()

    def prune_recent_topics(self, before: datetime) -> None:
        """created_at < before 인 오래된 행 삭제(테이블 무한 증가 방지)."""
        self._conn.execute(
            "DELETE FROM recent_topics WHERE created_at < ?", (before.isoformat(),)
        )
        self._conn.commit()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_state_repo.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/repositories/state_repo.py tests/test_state_repo.py
git commit -F - <<'EOF'
refactor: sent_hash 제거하고 의미 기반 recent_topics 저장소 추가

미배선 죽은 코드(sent_hash/was_sent/mark_sent)를 제거하고,
발송 토픽 텍스트를 TTL과 함께 저장하는 recent_topics 테이블·CRUD를 추가한다.
cross-run 중복 필터의 "최근 기억" 저장소로 사용.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

> 참고: 운영 state.db에 이미 있는 빈 `sent_hash` 테이블은 DDL 제거로 자동 삭제되지 않으나 비어 있어 무해하다(마이그레이션 불필요).

---

### Task 2: pre_cluster — 임베딩 모델 주입(선택 인자)

**Files:**
- Modify: `src/services/pre_cluster.py`

- [ ] **Step 1: 생성자 변경** — `PreClusterService.__init__`(47~49행)을 아래로 교체한다. 모델을 주입받되, 없으면 기존처럼 기본 모델을 로드해 **하위 호환**을 유지한다(main.py는 Task 7에서 주입으로 전환).

```python
    def __init__(
        self,
        threshold: float,
        model: SentenceTransformer | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self._threshold = threshold
        self._model = model if model is not None else SentenceTransformer(model_name)
```

- [ ] **Step 2: 기존 테스트로 회귀 확인** (동작 보존 리팩터 — 새 테스트 불필요)

Run: `python -m pytest tests/test_pre_cluster.py -v`
Expected: PASS (4개 — 순수 함수 `_union_find_groups`는 영향 없음)

- [ ] **Step 3: 타입 체크**

Run: `python -m mypy src/services/pre_cluster.py`
Expected: 에러 없음 (mypy 미설치 시 `pip install mypy` 후 실행, 또는 이 단계 건너뛰고 사유 보고)

- [ ] **Step 4: 커밋**

```bash
git add src/services/pre_cluster.py
git commit -F - <<'EOF'
refactor: PreClusterService에 임베딩 모델 주입 인자 추가

recent_dedup과 MiniLM 모델을 공유해 이중 로드를 막기 위한 선행 변경.
인자 미전달 시 기존처럼 기본 모델을 로드해 하위 호환 유지.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: recent_dedup 서비스 + 테스트

**Files:**
- Create: `src/services/recent_dedup.py`
- Test: `tests/test_recent_dedup.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_recent_dedup.py` 생성.

```python
"""RecentDedupService 및 _drop_indices 단위 테스트(임베딩 모델 미로드)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository
from src.services.recent_dedup import RecentDedupService, _drop_indices


def test_drop_indices_basic() -> None:
    sim = np.array([[0.9, 0.1], [0.2, 0.3]], dtype=np.float32)
    assert _drop_indices(sim, 0.85) == {0}


def test_drop_indices_empty() -> None:
    assert _drop_indices(np.empty((0, 0), dtype=np.float32), 0.85) == set()
    assert _drop_indices(np.empty((3, 0), dtype=np.float32), 0.85) == set()


class _FakeModel:
    """텍스트→고정 벡터 매핑을 정규화해 반환하는 가짜 임베더."""

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def encode(
        self,
        texts: list[str],
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> np.ndarray:
        vecs = np.array([self._mapping[t] for t in texts], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms


def _msg(text: str, mid: int) -> RawMessage:
    return RawMessage(
        channel_username="ch",
        message_id=mid,
        posted_at=datetime(2026, 7, 13, tzinfo=UTC),
        text=text,
    )


def test_filter_new_drops_duplicate(tmp_path: Path) -> None:
    model = _FakeModel(
        {"삼성 실적": [1.0, 0.0], "삼성전자 실적 발표": [1.0, 0.0], "환율 뉴스": [0.0, 1.0]}
    )
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, tzinfo=UTC)
        repo.add_recent_topics(["삼성 실적"], t0)
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new(
            [_msg("삼성전자 실적 발표", 1), _msg("환율 뉴스", 2)],
            now=t0 + timedelta(hours=1),
        )
        assert [m.text for m in kept] == ["환율 뉴스"]
    finally:
        repo.close()


def test_filter_new_empty_store_keeps_all(tmp_path: Path) -> None:
    model = _FakeModel({"a": [1.0, 0.0]})
    repo = StateRepository(tmp_path / "s.db")
    try:
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new([_msg("a", 1)], now=datetime(2026, 7, 13, tzinfo=UTC))
        assert len(kept) == 1
    finally:
        repo.close()


def test_filter_new_outside_window_keeps(tmp_path: Path) -> None:
    """기억이 창(24h) 밖이면 비교 대상에서 빠져 메시지가 유지된다."""
    model = _FakeModel({"삼성 실적": [1.0, 0.0], "삼성전자 실적 발표": [1.0, 0.0]})
    repo = StateRepository(tmp_path / "s.db")
    try:
        t0 = datetime(2026, 7, 13, tzinfo=UTC)
        repo.add_recent_topics(["삼성 실적"], t0)
        svc = RecentDedupService(0.85, 24, repo, model)  # type: ignore[arg-type]
        kept = svc.filter_new(
            [_msg("삼성전자 실적 발표", 1)], now=t0 + timedelta(hours=25)
        )
        assert len(kept) == 1
    finally:
        repo.close()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_recent_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.recent_dedup'`

- [ ] **Step 3: 서비스 구현** — `src/services/recent_dedup.py` 생성.

```python
"""실행 간(cross-run) 의미 중복 필터.

최근 window 시간 내 발송한 토픽과 의미가 유사한 새 메시지를 enrichment·요약 전에 제거한다.
임베딩은 pre_cluster와 동일한 SentenceTransformer를 주입받아 재사용한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np
from loguru import logger
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from src.dtos import RawMessage
from src.repositories.state_repo import StateRepository

_DROP_LOG_SNIPPET = 40  # 제거 로그에 남길 본문 길이


def _drop_indices(sim: NDArray[np.float32], threshold: float) -> set[int]:
    """sim[i][j]=메시지 i vs 최근 텍스트 j 유사도. 행별 최대가 threshold 이상인 메시지 인덱스."""
    if sim.size == 0:
        return set()
    max_per_row = sim.max(axis=1)
    return {int(i) for i in np.nonzero(max_per_row >= threshold)[0]}


class RecentDedupService:
    """최근 발송 토픽과 유사한 새 메시지를 제거하는 서비스."""

    def __init__(
        self,
        threshold: float,
        window_hours: int,
        state: StateRepository,
        model: SentenceTransformer,
    ) -> None:
        self._threshold = threshold
        self._window = timedelta(hours=window_hours)
        self._state = state
        self._model = model

    def filter_new(
        self, messages: list[RawMessage], now: datetime | None = None
    ) -> list[RawMessage]:
        """최근 발송 토픽과 유사한 메시지를 제거하고 나머지를 반환."""
        current = now or datetime.now(UTC)
        since = current - self._window
        recent_texts = self._state.get_recent_topic_texts(since)
        if not messages or not recent_texts:
            return messages
        sim = self._similarity(messages, recent_texts)
        drop = _drop_indices(sim, self._threshold)
        return self._log_and_keep(messages, sim, drop)

    def _similarity(
        self, messages: list[RawMessage], recent_texts: list[str]
    ) -> NDArray[np.float32]:
        """새 메시지 × 최근 텍스트 cosine 유사도 행렬."""
        msg_emb = self._model.encode(
            [m.text or "" for m in messages],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        rec_emb = self._model.encode(
            recent_texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return cast(NDArray[np.float32], msg_emb @ rec_emb.T)

    def _log_and_keep(
        self,
        messages: list[RawMessage],
        sim: NDArray[np.float32],
        drop: set[int],
    ) -> list[RawMessage]:
        """제거 건을 로그로 남기고 유지 목록을 반환."""
        kept: list[RawMessage] = []
        for i, m in enumerate(messages):
            if i not in drop:
                kept.append(m)
                continue
            snippet = (m.text or "").replace("\n", " ")[:_DROP_LOG_SNIPPET]
            best = float(sim[i].max())
            logger.info(
                f"[recent-dedup] drop ({m.channel_username}) sim={best:.3f} | {snippet}"
            )
        logger.info(
            f"recent-dedup: 총 {len(messages)}건 → 유지 {len(kept)}건(제거 {len(drop)}건)"
        )
        return kept
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_recent_dedup.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 커밋**

```bash
git add src/services/recent_dedup.py tests/test_recent_dedup.py
git commit -F - <<'EOF'
feat: cross-run 의미 중복 필터 서비스 추가

최근 window 내 발송 토픽과 cosine 유사도가 임계값 이상인 새 메시지를
요약 전에 제거한다. 임베딩 모델은 주입받아 pre_cluster와 공유.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: config — 설정 추가

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: 설정 필드 추가** — `src/config.py`의 `dedupe_threshold: float = 0.82`(47행) 바로 아래에 추가한다.

```python
    recent_dedup_threshold: float = 0.85
    recent_dedup_window_hours: int = 24
```

- [ ] **Step 2: 로드 확인**

Run: `python -c "from src.config import Settings; s = Settings(); print(s.recent_dedup_threshold, s.recent_dedup_window_hours)"`
Expected: `0.85 24` (필수 env 미설정 에러가 나면 `.env`가 있는 상태에서 실행)

- [ ] **Step 3: 커밋**

```bash
git add src/config.py
git commit -F - <<'EOF'
feat: recent_dedup 임계값·기억 창 설정 추가

recent_dedup_threshold(0.85)·recent_dedup_window_hours(24) 기본값.
env로 오버라이드 가능.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: 오프라인 검증 스크립트

**Files:**
- Create: `scripts/validate_recent_dedup.py`

- [ ] **Step 1: 스크립트 작성** — `scripts/validate_recent_dedup.py` 생성. 최근 48h를 수집해 24h 이전(memory)과 이내(new)로 나눠, 여러 임계값에서 제거 건수와 근거를 출력한다. **API 비용 없음**(Telethon 수집 + 로컬 임베딩만; ticker_extractor는 구성만 하고 LLM 미호출).

```python
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
    if not memory or not new:
        print(f"⚠ memory={len(memory)}건 / new={len(new)}건 — 한쪽이 비어 비교 불가.")
        return
    mem_emb = model.encode(
        [m.text or "" for m in memory], normalize_embeddings=True, convert_to_numpy=True
    )
    new_emb = model.encode(
        [m.text or "" for m in new], normalize_embeddings=True, convert_to_numpy=True
    )
    sim = new_emb @ mem_emb.T
    best = sim.max(axis=1)
    best_j = sim.argmax(axis=1)
    for th in _THRESHOLDS:
        drops = int((best >= th).sum())
        print(f"\n=== threshold {th:.2f}: new {len(new)}건 중 {drops}건 제거 ===")
        if abs(th - _DETAIL_TH) < 1e-9:
            for i in range(len(new)):
                if best[i] >= th:
                    print(
                        f"  drop sim={best[i]:.3f}\n"
                        f"    new : {_snip(new[i].text)}\n"
                        f"    ↔mem: {_snip(memory[int(best_j[i])].text)}"
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
```

- [ ] **Step 2: 구문·import 정상 확인** (네트워크 없이 로드만)

Run: `python -c "import ast; ast.parse(open('scripts/validate_recent_dedup.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add scripts/validate_recent_dedup.py
git commit -F - <<'EOF'
feat: cross-run 중복 필터 오프라인 검증 스크립트 추가

최근 48h 실제 데이터를 24h 경계로 나눠 여러 임계값의 제거 건수·근거를 출력.
배포 전 과필터 여부 확인용. Anthropic API 비용 없음.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: 🔑 오프라인 검증 게이트 (사용자 승인 필요 — 배선 전 필수)

**이 태스크는 코드 변경이 아니라 사람의 판단 게이트다. 통과 전 Task 7 금지.**

- [ ] **Step 1: 검증 실행** (`.env`가 있는 로컬에서)

Run: `python -m scripts.validate_recent_dedup`
Expected: `필터 후 N건 → memory M건 / new K건` + 임계값별 제거 건수 + 0.85 상세 목록.

- [ ] **Step 2: 사용자에게 제거 목록 제시** — threshold 0.85에서 제거될 `new` 메시지 목록과 매칭된 memory를 사용자에게 보여주고 **"진짜 새 소식이 잘못 걸리는 건 없는지"** 확인받는다.

- [ ] **Step 3: 파라미터 확정** — 사용자 판단에 따라 최종 `recent_dedup_threshold`를 정한다(과필터가 있으면 0.90로 상향, 너무 안 걸리면 0.80로 하향). 값 변경 시 `src/config.py` 기본값을 수정하고 커밋한다.

- [ ] **Step 4: 저장 텍스트 형태 확정** — 검증에서 raw-vs-raw 매칭이 실제로 유효하면 계획대로 진행. 매칭이 약하면(예: 발송 요약과 원문 분포 차이로 놓침) Task 7의 발송분 기록을 `제목+요약` 대신 **대표 멤버 raw 텍스트** 저장으로 전환하는 것을 검토(설계 문서 "배포 전 검증" 참조).

- [ ] **Step 5: 승인 확인** — 사용자 "진행" 확인을 받은 뒤에만 Task 7로 이동.

---

### Task 7: main.py 배선 + 발송분 기록 (검증 통과 후에만)

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: import 추가** — `src/main.py` 상단 import 블록을 수정한다.
  - `from datetime import UTC, datetime, timedelta` 추가(현재 없음).
  - `from sentence_transformers import SentenceTransformer` 추가.
  - 기존 `from src.services.pre_cluster import PreClusterService`를 `from src.services.pre_cluster import DEFAULT_MODEL_NAME, PreClusterService`로 교체.
  - `from src.services.recent_dedup import RecentDedupService` 추가.

- [ ] **Step 2: `_analyze`에 모델 주입** — `_analyze`(77~96행)의 시그니처에 `model` 파라미터를 추가하고, `PreClusterService(settings.dedupe_threshold)`를 `PreClusterService(settings.dedupe_threshold, model)`로 바꾼다.

```python
def _analyze(
    settings: Settings,
    state: StateRepository,
    client: Anthropic,
    msgs: list[RawMessage],
    ticker_dict: TickerDict,
    ticker_extractor: TickerExtractor,
    model: SentenceTransformer,
) -> list[OutboundBlock]:
    """필터된 메시지를 enrichment → pre_cluster → summarize → stock 순으로 파이프라인."""
    article_fetcher = ArticleFetcher(state)
    vision = VisionService(client, settings.model, state)
    enrichment = EnrichmentService(article_fetcher, ticker_extractor, vision)
    pre_cluster = PreClusterService(settings.dedupe_threshold, model)
    summarizer = DedupeSummarizerService(client, settings.model)

    enriched = [enrichment.enrich(m) for m in msgs]
    clusters = pre_cluster.cluster(enriched)
    topics = summarizer.summarize(clusters)
    stock = StockService(ticker_dict)
    return _build_blocks(topics, stock)
```

- [ ] **Step 3: 헬퍼 3개 추가** — `_analyze` 아래에 추가한다.

```python
def _dedup_recent(
    settings: Settings,
    state: StateRepository,
    model: SentenceTransformer,
    msgs: list[RawMessage],
) -> list[RawMessage]:
    """cross-run 중복 제거. 실패 시 graceful degrade(전체 유지)."""
    dedup = RecentDedupService(
        settings.recent_dedup_threshold, settings.recent_dedup_window_hours, state, model
    )
    try:
        return dedup.filter_new(msgs)
    except Exception as e:  # noqa: BLE001
        logger.error(f"recent-dedup 실패, 전체 유지: {e}")
        return msgs


def _process(
    settings: Settings,
    state: StateRepository,
    client: Anthropic,
    raw_msgs: list[RawMessage],
    window: Window,
) -> tuple[list[str], list[ClusteredTopic]]:
    """수집분을 필터·중복제거·분석해 (발송 메시지, 발송 토픽)을 반환."""
    if not raw_msgs:
        return build_messages(window, []), []
    ticker_dict = TickerDict(settings.state_db_path.parent)
    ticker_extractor = TickerExtractor(ticker_dict, client, settings.model)
    kept_msgs = filter_messages(raw_msgs, ticker_extractor)
    if not kept_msgs:
        return build_messages(window, []), []
    model = SentenceTransformer(DEFAULT_MODEL_NAME)
    fresh_msgs = _dedup_recent(settings, state, model, kept_msgs)
    if not fresh_msgs:
        # 전부 최근에 다룬 주제 — "새 정보 없음" 정상 발송
        return build_messages(window, []), []
    blocks = _analyze(
        settings, state, client, fresh_msgs, ticker_dict, ticker_extractor, model
    )
    if not blocks:
        raise RuntimeError(
            f"분석 파이프라인 결과 없음 (중복제거 후 {len(fresh_msgs)}건 있음) "
            "— Claude 응답 또는 JSON 파싱 확인 필요"
        )
    return build_messages(window, blocks), [b.topic for b in blocks]


def _record_sent_topics(
    state: StateRepository, topics: list[ClusteredTopic], window_hours: int
) -> None:
    """발송 토픽의 제목+요약을 recent_topics에 기록하고 오래된 항목을 프루닝."""
    try:
        now = datetime.now(UTC)
        if topics:
            state.add_recent_topics([f"{t.title}\n{t.summary}" for t in topics], now)
            logger.info(f"recent_topics 기록 {len(topics)}건")
        state.prune_recent_topics(now - timedelta(hours=window_hours * 2))
    except Exception as e:  # noqa: BLE001
        logger.error(f"recent_topics 기록/프루닝 실패: {e}")
```

- [ ] **Step 4: `_run` 본문 교체** — `_run`(115~164행)에서 수집 이후 분석·발송·갱신 부분을 아래로 교체한다(상단 `settings`/`state`/`client`/`TelethonRepository`/`collect` 부분은 그대로 유지).

```python
        logger.info(f"총 {len(raw_msgs)}건 수집")

        messages, sent_topics = _process(settings, state, client, raw_msgs, window)
        await _deliver(settings, messages, dry_run)

        # last_seen·recent_topics 갱신: dry_run/no_commit이면 건너뜀
        if dry_run:
            return
        if no_commit:
            logger.info("--no-commit 옵션 — last_seen·recent_topics 갱신 생략")
            return
        if raw_msgs:
            collector.commit_last_seen(raw_msgs)
            logger.info("last_seen 갱신 완료")
        _record_sent_topics(state, sent_topics, settings.recent_dedup_window_hours)
```

- [ ] **Step 5: 전체 테스트 실행**

Run: `python -m pytest -q`
Expected: 기존 통과 수 + 신규(recent_dedup 5 + state_repo 2, sent_hash 1 제거) 반영해 전체 PASS.

- [ ] **Step 6: dry-run 수동 검증** (`.env` 있는 로컬)

Run: `python -m src.main --window auto --dry-run`
Expected: 로그에 `recent-dedup: 총 N건 → 유지 M건(제거 K건)`가 찍히고, 콘솔에 요약 메시지 미리보기 출력. 에러 없이 종료.

- [ ] **Step 7: 커밋**

```bash
git add src/main.py
git commit -F - <<'EOF'
feat: cross-run 의미 중복 필터를 파이프라인에 배선

저가치 필터 직후 recent_dedup으로 최근 발송 토픽과 유사한 메시지를 제거하고,
발송 성공 후 토픽 제목+요약을 recent_topics에 기록한다. 임베딩 모델은
pre_cluster와 공유. 전부 중복이면 "새 정보 없음" 정상 발송, dedup 실패는 전체 유지.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 8: 문서 동기화

**Files:**
- Modify: `USER_ACTIONS.md`

- [ ] **Step 1: 검증 절차 추가** — `USER_ACTIONS.md`에 아래 항목을 적절한 위치(운영·점검 절차 근처)에 추가한다.

```markdown
## cross-run 중복 필터 검증 (배포/임계값 조정 시)
- 목적: 최근 발송 주제와 유사한 새 글을 요약 전에 걸러 비용·반복을 줄이는 필터가
  "진짜 새 소식"까지 지우지 않는지 실제 데이터로 확인.
- 실행: `python -m scripts.validate_recent_dedup` (`.env` 필요, Anthropic 비용 없음)
- 판정: threshold 0.85 상세 목록에서 잘못 걸린 새 소식이 있으면 `src/config.py`의
  `recent_dedup_threshold`를 0.90로 상향, 너무 안 걸리면 0.80로 하향.
```

- [ ] **Step 2: 커밋**

```bash
git add USER_ACTIONS.md
git commit -F - <<'EOF'
docs: cross-run 중복 필터 검증 절차를 USER_ACTIONS에 추가

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Self-Review 결과

- **Spec 커버리지**: recent_topics 저장소(Task 1) / sent_hash 제거(Task 1) / 모델 공유(Task 2,7) / RecentDedupService(Task 3) / config(Task 4) / graceful degrade(Task 3,7) / 발송분 기록·프루닝(Task 7) / 테스트(Task 1,3) / 오프라인 검증 게이트(Task 5,6) / 문서(Task 8) — 설계 문서 모든 절 대응 확인.
- **프루닝 위치**: 설계에선 filter_new 내부 프루닝이었으나, dry-run에서 상태 변경을 피하려 **조회 시 WHERE로 창 밖 제외 + 프루닝은 커밋 단계(_record_sent_topics)**로 분리(개선). 정확성은 조회 필터가 보장, 프루닝은 테이블 증가 방지용.
- **타입 일관성**: `filter_new(messages, now=None)`, `_drop_indices(sim, threshold)`, `add_recent_topics(texts, now)`, `get_recent_topic_texts(since)`, `prune_recent_topics(before)`, `_analyze(..., model)` — 태스크 간 시그니처 일치 확인.
- **플레이스홀더**: 없음(모든 코드 단계에 실제 코드 포함).
