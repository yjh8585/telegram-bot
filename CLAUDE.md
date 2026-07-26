# telegram-bot 프로젝트 규약 (Claude용)

## 프로젝트 정체
사용자 요청으로 만드는 **Python 3.12** 기반 텔레그램 채널 요약 봇.
상세 동작 규칙은 `ROADMAP.md`·`USER_ACTIONS.md`를 참조.

> ⚠️ 사용자 글로벌 CLAUDE.md는 Next.js 기본 스택을 전제로 하지만, 이 프로젝트는 **FinanceDataReader·Telethon이 Python 전용**이어서 Python 단일 구성으로 진행하기로 합의된 프로젝트다.
> 글로벌 규칙 중 "레이어드 아키텍처", "DTO", "에러 핸들링 필수", "한국어 주석·문서·커밋" 등 언어 중립 규칙은 아래에 Python 맥락으로 재서술했다.

## 언어 / 런타임
- Python 3.12 이상. `__future__` import 불필요.
- 타입 힌트 **필수**. `Any` 사용 금지(불가피하면 `object` + 구체 체크 또는 `typing.cast`).
- dataclass / pydantic 중 **pydantic v2 `BaseModel`** 을 DTO 표준으로.

## 코딩 스타일
- 변수·함수명: **snake_case** (사용자 글로벌 CLAUDE.md의 camelCase는 JS/TS 관례이며, Python PEP 8을 따름).
  - 클래스: PascalCase. 상수: UPPER_SNAKE.
- 들여쓰기 **4 스페이스** (Python PEP 8).
- 함수 **30줄 이하**. 길면 분리.
- 매직 넘버 금지 — 모듈 상단 `UPPER_SNAKE` 상수로 정의.
- 라이브러리 재발명 금지. 이미 있으면 그것을 써라.
- 공통 로직은 `services/`·`repositories/`에 올려 재사용.

## 로깅
- `loguru` 단독 사용. `print` 금지.
- 민감 정보(토큰·세션 문자열·전화번호)는 로그에 남기지 않는다. 실수 방지용 필터가 필요하면 `src/logger.py`에 추가.
- API usage 토큰(`log_api_usage`)은 stdout→GitHub Actions 런 로그에만 남는다(로컬 파일 없음). 비용·토큰 분석: `gh run view <id> --log | grep 'usage\['`.
- 파이프라인 필터(`message_filter`·`recent_dedup`)의 제거 건은 사유·유사도·본문 일부를 INFO 로그로 남긴다(사후 감사). `recent_dedup`는 실행 간 중복 제거로, state.db(`recent_topics`)가 실행 사이 유지됨(Actions 캐시)을 전제로 한다.
- 채널별 비용 귀속: `message_filter` drop 로그엔 **채널명이 있어** `수집−제거`로 채널별
  필터 통과 수를 복원할 수 있다. 반면 `usage[vision]`·`usage[summarize]`엔 채널명이 없어
  채널별 분해는 불가(필요 시 `enrichment.py`에 채널명 로깅 추가).

## 아키텍처 (레이어드)
```
main.py  (진입점·오케스트레이션)
  └─ services/  (비즈니스 로직)
       └─ repositories/  (외부 시스템 접근: Telethon, SQLite)
```
- Service → Repository만 의존. 역방향 금지.
- 의존성 주입: 생성자 파라미터로 주입. 전역 싱글턴 금지.
- DTO는 `src/dtos.py`에 pydantic 모델로 모음.

## 에러 핸들링
- 외부 경계(Telethon, Anthropic, HTTP, FDR)는 모두 try/except로 감싸고, 실패 시 **graceful degrade**:
  - 시세 조회 실패 → 티커만 표기.
  - Vision 실패 → 이미지 설명 생략.
  - 특정 채널 FloodWait → 그 채널만 스킵, 나머지 진행.
- 최종 오케스트레이터에서 잡히지 않은 예외는 **자기 자신(봇)에게 에러 요약 DM** 전송 후 프로세스 종료.

## 테스트
- `pytest` 필수. 새 기능에는 테스트 동반.
- 외부 호출은 모두 mock(`respx`, `unittest.mock`).
- 포맷터는 `syrupy` 스냅샷 테스트로 회귀 방지.
- 전체 실행 ~100s(sentence-transformers 로딩). Bash 도구 기본 타임아웃(120s) 경계라
  콜드 캐시인 세션 첫 실행은 초과한다 — `timeout` 상향 또는 백그라운드 실행.

## 커밋
- 커밋 메시지는 **한국어**, 현재형 어미("~추가", "~수정", "~개선").
- 타입 prefix 권장: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- 중요 변경(파일 구조 변화, Phase 완료 등)마다 커밋.
- Bash 도구로 다중행 커밋 시 PowerShell here-string(`@'...'@`) 금지(POSIX 셸이라 `@`가 남음). `git commit -F - <<'EOF'` 사용.

## 문서화
- docstring·주석은 **한국어**.
- 공개 함수/클래스에 한 줄 docstring 필수. 복잡한 의사결정 배경만 주석으로.

## 커뮤니케이션 규칙 (Claude가 지킬 것)
- **모르거나 확실하지 않으면 반드시 질문**(사용자 글로벌 CLAUDE.md에도 명시됨).
- 파일을 새로 만들 때는 먼저 계획을 말하고 진행.
- 변경 이유를 간단히 설명.
- 에러 발생 시 원인과 해결 방법을 함께 제시.
- 사용자가 수동으로 해야 할 일은 `USER_ACTIONS.md`에 정리·유지.

## 비밀 관리
- `.env`, `*.session`, `state/*.db` 절대 커밋 금지 (`.gitignore`로 차단).
- 단 `.gitignore`는 `state/` 전체가 아니라 `state/*.db`만 막는다 —
  `state/krx_ticker_dict.json`은 추적 대상. `git add .` 대신 파일을 명시 스테이징.
- GitHub 배포 시 민감값은 **Secrets**로만 전달.

## 실행
> ⛔ **2026-07-27 운영 중단** — 비용 대비 효과 부족으로 GitHub Actions 워크플로를 `disabled_manually` 상태로 껐다.
> 코드는 그대로 두었고 `gh workflow enable "Telegram 채널 요약 수집·발송"` 한 번으로 재개된다. 상세는 `USER_ACTIONS.md` 최상단.
> `BOT_TOKEN`·`ANTHROPIC_API_KEY`는 VALLEY-AI 프로젝트와 공유하므로 폐기 금지.

- 로컬: `make dry-run` / `make run`
- CI: GitHub Actions (`.github/workflows/collect.yml`). 정각 트리거는 외부 `cron-job.org`가 `workflow_dispatch`로 호출 (GitHub 내장 cron 지연 회피). 운영·점검 절차는 `USER_ACTIONS.md` C-5 참조.
- 수집 채널은 `src/config.py`의 `CHANNELS` 튜플. 추가·삭제 시 `README.md`·`.claude/agents/telegram-bot-expert.md`의 채널 수 표기도 동기화. `tests/`의 채널명은 임의 픽스처이므로 함께 고치지 않는다.
