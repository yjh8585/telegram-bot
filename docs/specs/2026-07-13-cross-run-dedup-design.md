# 실행 간(cross-run) 의미 중복 필터 설계 (2026-07-13)

## 배경
- 사용자 관찰: "하루에도 여러 번, 그리고 며칠째 비슷한 글이 반복" + "비용이 아깝다".
- 현재 봇의 중복 제거 장치는 **한 번의 실행(run) 안에서만** 동작:
  1. 수집 중복 방지 `last_seen`/`min_id` — *똑같은* 메시지 재수집만 차단.
  2. 저가치 사전 필터 `message_filter` — 잡담·빈 차트 사진 제거.
  3. 유사도 클러스터링 `pre_cluster` — 실행 내 cosine ≥ 0.82 병합.
  4. LLM 통합 요약 `dedupe_summarizer`.
- **구멍**: `sent_hash` 테이블과 `was_sent`/`mark_sent`(발송 기억)가 만들어져 테스트까지 통과하지만
  `main.py` 파이프라인에서 **한 번도 호출되지 않는 죽은 코드**다. 즉 실행 간 중복 제거가 없어,
  하루 4회(아침·점심·오후·저녁) 발송 시 같은 주제가 실행을 넘어 반복되고 그때마다 vision·요약 비용이 재발생한다.
- 게다가 `sent_hash`는 **정확 해시** 비교라 "글자는 달라도 의미가 같은" 글을 못 잡는다.

## 목표
"이미 최근에 다룬 주제"를 기억했다가, 새로 들어온 메시지가 그것과 **의미상 비슷하면** enrichment·요약에
태우기 **전에** 제거한다. 이로써 vision·요약 토큰을 아끼고(비용↓) 실행/날짜를 넘는 반복을 없앤다(품질↑).

## 사용자 결정 사항
- **범위**: 실행 간(하루 안 여러 번) + 날짜 간(며칠째) 반복 모두 대상.
- **적용 지점**: 메시지 단계(요약 전). 원본 메시지를 임베딩해 최근 발송 토픽과 비교, 유사하면 파이프라인 전에 제거.
- **강도**: 균형 — 중간 임계값(0.85)·24h 기억 창. 배포 전 실제 데이터 검증을 통해 최종 보정.
- **죽은 코드**: `sent_hash`는 이 기능이 대체하므로 제거(사용자 승인 완료).

## 데이터 흐름
```
현재:  수집 → [저가치 필터] → enrich → pre_cluster → summarize → stock → 발송
개선:  수집 → [저가치 필터] → [★recent_dedup] → enrich → pre_cluster → summarize → stock → 발송
                                                                                            ↓
                                        발송 성공 후: 방금 보낸 토픽 텍스트를 recent_topics에 기록
```
버려진 메시지는 enrich(vision·기사수집·티커 LLM)와 summarize를 **아예 거치지 않는다** → 비용 절감의 핵심.

## 구성 요소

### 1) 저장소 — `recent_topics` 테이블 (state_repo)
```sql
CREATE TABLE IF NOT EXISTS recent_topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,   -- 발송한 토픽의 "제목 + 요약"
    created_at TEXT NOT NULL    -- UTC ISO. TTL 프루닝용
);
```
- 메서드:
  - `get_recent_topic_texts(since: datetime) -> list[str]` — `created_at >= since` 텍스트.
  - `add_recent_topics(texts: list[str], now: datetime) -> None` — 발송분 기록.
  - `prune_recent_topics(before: datetime) -> None` — TTL 초과 삭제.
- **임베딩 BLOB이 아니라 텍스트로 저장**하고 매 실행 재임베딩한다. 근거: (a) 저장물을 사람이 읽어
  감사 가능, (b) 임베딩 모델 교체 시에도 저장물이 깨지지 않음, (c) 텍스트 수백 개 재임베딩은 로컬 수 ms로 사실상 무료.
- 저장 텍스트는 사용자가 실제로 본 **`제목 + "\n" + 요약`**. (실제 raw 메시지와 분포가 달라 매칭이
  약하면, 대표 멤버의 raw 텍스트 저장으로 전환 — 아래 "배포 전 검증"에서 판정.)

### 2) 상태 저장소 정리 — `sent_hash` 제거
- `sent_hash` 테이블 DDL, `was_sent`/`mark_sent`, `tests/test_state_repo.py::test_sent_hash` 삭제.
- 이 기능이 의미 기반으로 대체하며 스키마(정확 해시 PK)가 다건 텍스트+TTL 용도와 맞지 않는다.

### 3) 새 서비스 — `src/services/recent_dedup.py`
`RecentDedupService.filter_new(messages: list[RawMessage]) -> list[RawMessage]`:
1. `now`·`since = now - window(24h)` 계산 → `since` 이전 기억 프루닝.
2. `recent_texts = get_recent_topic_texts(since)`. **비어 있으면 전부 통과**(비교 대상 없음).
3. 최근 텍스트 + 새 메시지 **원본 텍스트**를 임베딩(normalize) → cosine 유사도(메시지 × 최근) 계산.
   각 메시지의 최대 유사도가 **≥ threshold(0.85)** 이면 제거(사유·유사도·본문 일부 INFO 로그), 아니면 유지.
4. 요약 로그: `recent-dedup: 총 N건 → 유지 M건(제거 K건)`.
- 유사도 계산 핵심 로직은 모델과 분리된 **순수 함수**로 노출해 단위 테스트 가능하게 한다
  (`pre_cluster._union_find_groups`가 임베딩 로드 없이 테스트되는 방식과 동일).

### 4) 임베딩 모델 공유 (중복 로드 방지)
- 현재 `PreClusterService`가 생성 시 MiniLM(약 120MB)을 자체 로드한다. 여기서 또 로드하면 이중 낭비.
- `_analyze`에서 `SentenceTransformer`를 **한 번 생성**해 `PreClusterService`·`RecentDedupService`에 **주입**한다.
  - `PreClusterService.__init__(threshold, model)` 로 소폭 변경(모델 주입).
  - 기존 `DEFAULT_MODEL_NAME`은 모델 생성 위치(`_analyze` 또는 얇은 팩토리)로 이동.

### 5) 발송분 기록 (main.py)
- `_run`에서 발송 성공 후(`dry_run`/`no_commit` 아닐 때), `commit_last_seen` 옆에서
  방금 보낸 토픽들의 `제목+요약`을 `add_recent_topics`로 저장.

### 6) 설정 (config)
- `recent_dedup_threshold: float = 0.85`
- `recent_dedup_window_hours: int = 24`
- 기존 `dedupe_threshold`와 동일하게 env 오버라이드 가능. **on/off 플래그는 두지 않는다**
  (message_filter 설계 선례 — 문제 시 revert).

### 7) 에러 처리 (graceful degrade)
- `recent_dedup`가 예외를 던지면 → **전체 메시지를 그대로 유지**하고 에러 로그만 남긴다.
  중복 제거 실패 때문에 정보를 잃지 않는다.
- 발송분 기록 실패도 런을 죽이지 않는다(최악의 경우 다음 런의 중복 제거 범위만 줄어듦).

## 테스트
- `tests/test_recent_dedup.py` (외부 호출 없음, 가짜 임베더 주입으로 MiniLM 미로드):
  - 최근 토픽과 동일 주제 메시지 → 제거.
  - 무관한 메시지 → 유지.
  - 기억 없음(빈 저장소) → 전부 유지.
  - TTL 초과 기억 → 무시되어 메시지 유지.
  - 임계값 경계값 검증.
- `tests/test_state_repo.py`: `recent_topics` CRUD·프루닝 테스트 추가, `test_sent_hash` 제거.

## 배포 전 오프라인 검증 (핵심 게이트 — 사용자 요구)
`main.py` 배선·배포 **전에**, 최근 실제 수집 데이터(약 48h)에 이 필터를 적용해
**제거될 메시지 목록 + 유사도 점수 + 매칭된 이전 토픽**을 출력해 사용자 확인을 받는다.
과필터(진짜 새 소식 제거)가 없을 때만 배선·배포한다. 이 시점에 저장 텍스트 형태(제목+요약 vs 대표 raw)와
threshold 값을 실제 데이터로 최종 결정한다.

## 롤아웃 단계
- **A. 부품 구축**: `recent_topics` 테이블·`RecentDedupService`·config·테스트. `sent_hash` 제거. (main.py 미배선)
- **B. 오프라인 검증**: 검증 스크립트로 실제 데이터에 적용 → 제거 목록 사용자 리뷰 → threshold/저장형태 확정.
- **C. 배선·배포**: `_analyze`에 필터 삽입 + 발송분 기록 배선 → 배포. (B 통과 후에만)

## 배포 전 검증 결과 및 반영 (2026-07-13)
실제 최근 48h 데이터로 검증한 결과와 그에 따른 설계 보정:
- **URL 오탐 발견 → URL 제거 반영**: 링크만 있는 글은 임베딩이 URL 문자열 구조에 지배당해
  서로 다른 기사도 0.85~0.91로 유사하게 나왔다. 유사도 판단 전 `_strip_urls`로 URL을 제거하고,
  본문이 빈(링크만) 메시지는 비교에서 빼 무조건 유지하도록 `recent_dedup`을 보정.
- **짧은 글 스퍼리어스 유사도 → 임계값 0.90 확정**: URL 제거 후에도 짧고 모호한 글이 서로 다른
  뉴스를 0.85~0.89로 오탐. 0.90에서 명백한 오탐이 사라지고 남는 건은 반복 한탄성 글이라 잡는 게
  맞아 기본값을 0.85→0.90으로 상향. env(`RECENT_DEDUP_THRESHOLD`)로 조정 가능.
- **저장 형태**: 검증(원본 vs 원본)은 운영(원본 vs 토픽 요약)보다 짧은 글에 과격하므로, 계획대로
  `제목+요약` 저장을 유지. 운영에서 반복이 잘 안 걸리면 임계값 하향으로 관찰.

## 범위 밖 (YAGNI)
- LLM 기반 중복 판정(비용 취지에 자기모순).
- 토픽 단계(요약 후) 억제 — 메시지 단계가 부족하다고 판명되면 추후 추가.
- 채널 포맷 기반 규칙("며칠째 같은 종류"가 의미 비교로 안 잡히면 그때 도입).

## 되돌리기
문제 시 커밋 revert로 원복. 별도 on/off 플래그는 두지 않는다(필요 시 추후 추가).
