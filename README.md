# 텔레그램 채널 요약 봇

관심 텔레그램 채널 4개의 최신 메시지를 하루 4회(07:30 / 11:00 / 15:00 / 18:00 KST) 수집·중복 통합·요약하여 본인 계정(@yjh8585)으로 DM 전송.

## 대상 채널
- [@FastStockNews](https://t.me/FastStockNews)
- [@Yeouido_Lab](https://t.me/Yeouido_Lab)
- [@TNBfolio](https://t.me/TNBfolio)
- [@triple_stock](https://t.me/triple_stock)

## 발송 규칙
| 발송 시각(KST) | 수집 구간 |
|---|---|
| 07:30 | 전일 18:00 ~ 당일 07:30 |
| 11:00 | 07:30 ~ 11:00 |
| 15:00 | 11:00 ~ 15:00 |
| 18:00 | 15:00 ~ 18:00 |

## 중복 제거 계층
비용 절감과 반복 감소를 위해 여러 단계로 중복·저가치 메시지를 걸러낸다.
1. **수집 중복 방지**(`last_seen`) — 이미 읽은 메시지 재수집 차단.
2. **저가치 사전 필터**(`message_filter`) — 잡담·빈 차트 사진 제거.
3. **실행 간 의미 중복 필터**(`recent_dedup`) — 최근 발송한 토픽과 의미가 비슷한 새 메시지를
   요약 전에 제거(임베딩 cosine ≥ `RECENT_DEDUP_THRESHOLD`, 기억 창 `RECENT_DEDUP_WINDOW_HOURS`).
   URL은 유사도 판단에서 제외해 링크 오탐을 막는다. → 하루 안·날짜 간 반복 감소, vision·요약 비용 절감.
4. **실행 내 클러스터링**(`pre_cluster`) + **LLM 통합 요약**(`dedupe_summarizer`).

## 기술 스택
- Python 3.12
- Telethon (user session, MTProto)
- python-telegram-bot (DM 발송)
- Claude Haiku 4.5 (요약·중복 통합·vision)
- sentence-transformers (사전 클러스터링 + 실행 간 의미 중복 필터, 토큰 절감)
- FinanceDataReader (주가)
- GitHub Actions cron (스케줄)
- SQLite + actions/cache (상태 저장)

## 세팅

처음 세팅 시 **반드시 `USER_ACTIONS.md`의 단계별 안내**를 따라주세요.

빠른 개요:
```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채우기
python scripts/login.py       # Telethon 세션 생성
python scripts/get_chat_id.py # 봇 chat_id 확인
make dry-run                  # 테스트 실행
```

## 주요 명령
```bash
make test        # 단위 테스트
make dry-run     # 실제 수집 + stdout 출력 (DM 미발송)
make run         # 실제 DM 전송
make check-all   # lint + typecheck + test
```

## 문서
- [`USER_ACTIONS.md`](./USER_ACTIONS.md) — **사용자가 수동으로 수행해야 하는 작업 상세 가이드**
- [`CLAUDE.md`](./CLAUDE.md) — 프로젝트 코딩 규약
- [`ROADMAP.md`](./ROADMAP.md) — 구현 단계·진행 상황
