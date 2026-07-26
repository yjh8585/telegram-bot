# ROADMAP — 텔레그램 채널 요약 봇

> ⛔ **2026-07-27 운영 중단.** 비용 대비 효과가 낮다는 사용자 판단으로 발송을 멈췄다.
> GitHub Actions 워크플로가 `disabled_manually` 상태이며, 아래 미완료 Phase는 **재개 시에만** 유효하다.
> 재개·잔여 수동 작업은 [`USER_ACTIONS.md`](./USER_ACTIONS.md) 최상단 참조.

각 Phase의 완료 기준(DoD)을 명시. 체크박스는 실제 완료 시 업데이트.

## Phase 0 — 사전 준비 (사용자 수동) ✅
→ 전체 절차는 [`USER_ACTIONS.md`](./USER_ACTIONS.md).
- [x] BotFather 봇 생성 & `/start`
- [x] my.telegram.org api_id/api_hash
- [x] Anthropic API Key
- [x] Telethon 세션 발급
- [x] 봇 chat_id 확인
- [x] `.env` 작성

## Phase 1 — 스캐폴딩 ✅
- [x] 디렉토리 구조 생성
- [x] `pyproject.toml`, `requirements.txt`, `Makefile`, `.gitignore`, `.env.example`
- [x] `README.md`, `USER_ACTIONS.md`, `CLAUDE.md`, `ROADMAP.md`
- [x] `.claude/settings.json` (Shrimp MCP 등록)
- [x] `.claude/agents/telegram-bot-expert.md`
- [x] Python 패키지 `__init__.py`
- **DoD**: `pip install -r requirements.txt`가 통과하고 `pytest` 실행 가능.

## Phase 2 — 수집 레이어 ✅
- [x] `src/config.py` — pydantic-settings
- [x] `src/logger.py` — loguru + 민감정보 필터
- [x] `src/window.py` — KST 윈도우 판정
- [x] `src/dtos.py` — RawMessage, EnrichedMessage, ...
- [x] `src/repositories/state_repo.py` — SQLite (last_seen, url_cache, image_cache, sent_hash)
      ※ `sent_hash`는 Phase 10에서 `recent_topics`로 대체됨
- [x] `src/repositories/telethon_repo.py` — iter_messages, FloodWait
- [x] `src/services/collector.py`
- [x] `scripts/login.py`, `scripts/get_chat_id.py`
- **DoD**: `scripts/login.py`로 SESSION_STRING 발급 → `collector.fetch(window)` 가 샘플 채널에서 메시지를 받아오는 단위 테스트 통과.

## Phase 3 — Enrichment ✅
- [x] `src/services/article_fetcher.py` + url_cache
- [x] `src/services/vision.py` + image_cache (Claude vision)
- [x] `src/services/ticker_dict.py` — KRX 종목명↔코드 사전
- [x] `src/services/ticker_extractor.py` — 정규식·사전 1차, LLM 2차
      ※ LLM 2차 폴백은 Phase 11에서 기본 비활성화(비용 회피)
- **DoD**: 샘플 메시지에서 뉴스 본문·이미지 설명·티커를 추출하여 `EnrichedMessage` 반환.

## Phase 4 — Pre-cluster + 요약 ✅
- [x] `src/services/pre_cluster.py` — sentence-transformers + cosine≥0.82
- [x] `src/services/dedupe_summarizer.py` — Claude Haiku 4.5 structured output
- [x] `src/prompts/cluster_merge.md`
- **DoD**: 동일 주제 메시지 3건을 넣으면 `ClusteredTopic` 1건으로 병합되어 반환.

## Phase 5 — 주가 정보 ✅
- [x] `src/services/stock.py` — FDR 래퍼 + tenacity 재시도
- **DoD**: 한국/미국/코인 티커 각 1건씩 시세 반환, 실패 시 None 처리.

## Phase 6 — Formatter + Notifier ✅
- [x] `src/services/formatter.py` — MarkdownV2 이스케이프, 4096자 분할
- [x] `src/services/notifier.py` — Bot API sendMessage + 재시도
- **DoD**: 스냅샷 테스트 통과.

## Phase 7 — 오케스트레이션 ✅
- [x] `src/main.py` — 전체 파이프라인
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
- [x] `tests/test_message_filter.py` (저가치 사전 필터)
- [x] `tests/test_recent_dedup.py` (실행 간 중복 필터)
- [x] `tests/test_vision.py` (다운샘플·phash)
- **DoD**: `pytest` 90 passed ✅ (12개 파일)

## Phase 9 — GitHub Actions 배포 ✅
- [x] `.github/workflows/collect.yml` — `workflow_dispatch` 전용
      ※ GitHub 내장 cron은 수십 분 지연이 있어 제거. 정각 트리거는 외부
        `cron-job.org`가 `workflow_dispatch`를 호출한다 → `USER_ACTIONS.md` C-5
- [x] `actions/cache` 로 state 유지 (`state-v2-$run_id` 키)
- [x] HuggingFace 모델 캐시 (~120MB 절감)
- [x] 에러 시 봇 자신에게 DM (main.py `_report_error` 구현)
- **DoD**: GitHub Secrets 등록 후 `workflow_dispatch`로 수동 트리거 → 성공 확인.

## Phase 10 — 실행 간(cross-run) 의미 중복 필터 ✅
하루 안·날짜 간 반복되는 유사 주제를 요약 전에 제거해 vision·요약 비용을 줄인다.
- [x] `sent_hash`(미배선 죽은 코드) 제거 → `recent_topics`(text+TTL) 저장소로 대체
- [x] `src/services/recent_dedup.py` — 최근 발송 토픽과 cosine ≥ 임계값이면 제거, URL 제외
- [x] 임베딩 모델을 `pre_cluster`와 공유(이중 로드 방지)
- [x] `main.py` 배선: 저가치 필터 직후 중복 제거 + 발송 후 토픽 기록·프루닝
- [x] `scripts/validate_recent_dedup.py` — 배포 전 실제 데이터 오탐 검증
- [x] 검증 결과 임계값 0.90 확정(짧은 글 스퍼리어스 유사도 오탐 회피)
- **설계·계획**: `docs/specs/2026-07-13-cross-run-dedup-design.md`, `docs/plans/2026-07-13-cross-run-dedup.md`
- **DoD**: `pytest` 전체 통과 + dry-run에서 `recent-dedup` 로그 확인.

## Phase 11 — API 비용 절감 (2026-07-14) ✅
"호출 회피 + 토큰 축소"로 비용을 낮춘다. 콘텐츠를 버리는 레버는 기본 off.
- [x] ticker LLM 폴백 기본 비활성화(`enable_ticker_llm_fallback=False`) — 정규식·KRX 사전으로
      못 찾은 종목의 Claude 재추출 호출 회피. env로 되돌리기 가능
- [x] vision 다운샘플(장변 1024px, JPEG q85) + 유사이미지 phash 캐시
      — phash는 오탐 위험이 있어 **기본 shadow**(호출 유지·로그만). Actions 로그로
        오탐 없음 확인 후 `ENABLE_IMAGE_PHASH_CACHE=true`로 승격
- [x] summarize 입력 컷오프(`rep_text_limit` 2000→1600)·출력 압축(프롬프트)
      — 토픽 상한(`summarize_max_topics`)은 콘텐츠 손실 위험으로 **기본 0=off**
- **설계**: `docs/specs/2026-07-14-vision-cost-reduction.md`,
  `docs/specs/2026-07-14-summarize-compression.md`
- **DoD**: `pytest` 전체 통과 + 배포 후 DM 리뷰로 요약 품질 확인.
- **실측(2026-07-15, 런 6개)**: 런당 $0.1108 → 하루 4회 기준 월 약 $13.30.
  내역 summarize 69.2% / vision 30.8%. 측정 방법은 `CLAUDE.md`의 로깅 절 참조.

## Phase 12 — 수집 채널 조정 (2026-07-15) ✅
- [x] `FastStockNews` 제외 — 투자뉴스 범위가 너무 넓어 개인 관심사와 불일치.
      수집 채널 4개 → 3개. **비용이 아닌 관련성이 사유**
      (필터 제거율은 8.3%로 4개 중 가장 낮았음 — 신호 밀도 지표는
       "사용자에게 의미 있는가"를 측정하지 못한다)
- [x] `README.md`·`.claude/agents/telegram-bot-expert.md` 채널 수·목록 동기화
- **DoD**: `pytest` 전체 통과 + `CHANNELS` 로드값 3개 확인.
