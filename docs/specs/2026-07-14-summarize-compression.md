# summarize 비용 압축 설계 (2026-07-14)

## 배경
- 실측: API 비용의 약 61%가 `summarize`. 그 내부는 **입력 57% / 출력 43%**
  (입력 = 클러스터 대표 본문 × 클러스터 수, 출력 = 토픽별 title+summary).
- 출력 토큰 단가는 입력의 5배지만, 입력 토큰 양이 훨씬 많아 dollar 기준으로는 입력이 더 큼.

## 레버
### (a) 출력 압축 — 프롬프트 (기본 적용)
- `cluster_merge.md`의 summary 지시를 "3~5문장" → "2~3문장, 핵심 사실·수치·시장영향만 간결히, 배경·수식 생략".
- 사용자가 읽는 DM 본문이 짧아짐 — **user-visible 변경**. 과하지 않게 중간 강도로 조정.

### (c) 입력 컷오프 — rep_text_limit (기본 2000→1600)
- 클러스터 대표 본문을 `summarize_rep_text_limit`(config, env 조정 가능)자로 절단.
- 2000→1600은 기사 본문이 긴 클러스터의 입력만 줄이고, 짧은 메시지엔 영향 없음.

### (b) 토픽 상한 — max_topics (기본 0=끔)
- `summarize_max_topics`>0이면 **멤버수(신호 강도) 상위 N개** 클러스터만 요약하고 나머지는 제거(INFO 로그).
- **콘텐츠 손실 위험**(단일 채널 특종이 멤버 적어 잘릴 수 있음)이 있어 **기본 비활성**.
  헤비한 날 비용이 급증할 때만 env로 켠다. 2b(phash) opt-in과 동일 철학.

## 검증
- summarize는 LLM 호출이라 필터·dedup처럼 배포 전 오프라인(무-API) 검증이 불가.
  → **검증 게이트 = 배포 후 실제 DM 리뷰**. (a) 요약이 과하게 짧지 않은지 다음 몇 회 DM으로 확인.
- (a)·(c)는 콘텐츠를 버리지 않고 토픽당 비용만 낮춤. (b)만 콘텐츠를 버리므로 기본 off.
- 되돌리기: 프롬프트 revert + `SUMMARIZE_REP_TEXT_LIMIT`·`SUMMARIZE_MAX_TOPICS` env로 즉시 조정.

## 부수 정리
- `dedupe_summarizer.py`의 기존 import 정렬 nit(json_repair↔anthropic 빈 줄) 함께 수정.
