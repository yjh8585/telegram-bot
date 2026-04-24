# ROADMAP — 텔레그램 채널 요약 봇

각 Phase의 완료 기준(DoD)을 명시. 체크박스는 실제 완료 시 업데이트.

## Phase 0 — 사전 준비 (사용자 수동)
→ 전체 절차는 [`USER_ACTIONS.md`](./USER_ACTIONS.md).
- [ ] BotFather 봇 생성 & `/start`
- [ ] my.telegram.org api_id/api_hash
- [ ] Anthropic API Key
- [ ] Telethon 세션 발급
- [ ] 봇 chat_id 확인
- [ ] `.env` 작성

## Phase 1 — 스캐폴딩 ✅
- [x] 디렉토리 구조 생성
- [x] `pyproject.toml`, `requirements.txt`, `Makefile`, `.gitignore`, `.env.example`
- [x] `README.md`, `USER_ACTIONS.md`, `CLAUDE.md`, `ROADMAP.md`
- [x] `.claude/settings.json` (Shrimp MCP 등록)
- [x] `.claude/agents/telegram-bot-expert.md`
- [x] Python 패키지 `__init__.py`
- **DoD**: `pip install -r requirements.txt`가 통과하고 `pytest` 실행 가능.

## Phase 2 — 수집 레이어
- [ ] `src/config.py` — pydantic-settings
- [ ] `src/logger.py` — loguru + 민감정보 필터
- [ ] `src/window.py` — KST 윈도우 판정
- [ ] `src/dtos.py` — RawMessage, EnrichedMessage, ...
- [ ] `src/repositories/state_repo.py` — SQLite (last_seen, url_cache, image_cache, sent_hash)
- [ ] `src/repositories/telethon_repo.py` — iter_messages, FloodWait
- [ ] `src/services/collector.py`
- [ ] `scripts/login.py`, `scripts/get_chat_id.py`
- **DoD**: `scripts/login.py`로 SESSION_STRING 발급 → `collector.fetch(window)` 가 샘플 채널에서 메시지를 받아오는 단위 테스트 통과.

## Phase 3 — Enrichment
- [ ] `src/services/article_fetcher.py` + url_cache
- [ ] `src/services/vision.py` + image_cache (Claude vision)
- [ ] `src/services/ticker_dict.py` — KRX 종목명↔코드 사전
- [ ] `src/services/ticker_extractor.py` — 정규식·사전 1차, LLM 2차
- **DoD**: 샘플 메시지에서 뉴스 본문·이미지 설명·티커를 추출하여 `EnrichedMessage` 반환.

## Phase 4 — Pre-cluster + 요약
- [ ] `src/services/pre_cluster.py` — sentence-transformers + cosine≥0.82
- [ ] `src/services/dedupe_summarizer.py` — Claude Haiku 4.5 structured output
- [ ] `src/prompts/cluster_merge.md`
- **DoD**: 동일 주제 메시지 3건을 넣으면 `ClusteredTopic` 1건으로 병합되어 반환.

## Phase 5 — 주가 정보
- [ ] `src/services/stock.py` — FDR 래퍼 + tenacity 재시도
- **DoD**: 한국/미국/코인 티커 각 1건씩 시세 반환, 실패 시 None 처리.

## Phase 6 — Formatter + Notifier
- [ ] `src/services/formatter.py` — MarkdownV2 이스케이프, 4096자 분할
- [ ] `src/services/notifier.py` — Bot API sendMessage + 재시도
- **DoD**: 스냅샷 테스트 통과.

## Phase 7 — 오케스트레이션
- [ ] `src/main.py` — 전체 파이프라인
- **DoD**: `make dry-run` 성공 (DM 미발송, state 미갱신).

## Phase 8 — 테스트 ✅
- [x] `tests/test_window.py`
- [x] `tests/test_pre_cluster.py`
- [x] `tests/test_ticker_extractor.py`
- [x] `tests/test_article_fetcher.py` (캐시 히트/미스)
- [x] `tests/test_formatter.py` (스냅샷)
- [x] `tests/test_stock.py`
- [x] `tests/test_state_repo.py`
- [x] `tests/test_collector.py`
- [x] `tests/test_dedupe_summarizer.py`
- **DoD**: `pytest` 49 passed ✅

## Phase 9 — GitHub Actions 배포 ✅
- [x] `.github/workflows/collect.yml` — 4개 cron + workflow_dispatch
- [x] `actions/cache` 로 state 유지 (state-$run_id 키)
- [x] HuggingFace 모델 캐시 (~120MB 절감)
- [x] 에러 시 봇 자신에게 DM (main.py `_report_error` 구현)
- **DoD**: GitHub Secrets 등록 후 `workflow_dispatch`로 수동 트리거 → 성공 확인.
