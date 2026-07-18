# 사용자가 수동으로 수행해야 할 일

Claude가 자동화할 수 없는 단계를 모두 여기에 정리했다. **번호 순서대로** 진행하면 된다.
완료한 항목은 체크박스를 채워 진행 상황을 관리할 수 있다.

---

## A. 계정·API 키 발급 (한 번만)

### A-1. Python 3.12 설치 확인
- [ ] 터미널에서 `python --version` 또는 `py -3.12 --version` 실행
- 없다면 https://www.python.org/downloads/ 에서 3.12 이상 설치

### A-2. Telegram Bot 생성 (BotFather)
- [ ] Telegram 앱에서 **@BotFather** 검색 → 대화 시작
- [ ] `/newbot` 입력 → 봇 이름, 사용자명(예: `yjh_news_bot`) 순서대로 입력
- [ ] **BOT_TOKEN** 을 기록 (형식: `123456:ABC-...`)
- [ ] 생성된 봇 링크(BotFather가 응답으로 줌)를 눌러 그 봇에게 **`/start`** 를 1회 보내기
  - 이 단계를 하지 않으면 봇이 나에게 DM을 보낼 수 없다.

### A-3. Telegram API 앱 등록 (user session 용)
- [ ] https://my.telegram.org 에 접속 → 전화번호로 로그인
- [ ] 상단 **API development tools** 클릭 → **Create new application**
- [ ] App title, Short name 등은 아무렇게나 (예: `news-bot`, `newsbot`)
- [ ] Platform: `Other`
- [ ] 등록 후 나오는 **api_id**, **api_hash** 를 기록 (이후 숨겨짐)

### A-4. Anthropic API Key 발급
- [ ] https://console.anthropic.com 접속 → 로그인
- [ ] **API Keys** → **Create Key** → 이름(예: `telegram-bot`) → 생성
- [ ] 출력된 **ANTHROPIC_API_KEY** 를 기록 (형식: `sk-ant-...`)
- [ ] 결제 수단 등록 — Claude Haiku 4.5는 월 $2~4 수준 예상 (최적화 적용 시)

---

## B. 로컬 세팅

### B-1. 의존성 설치
```bash
cd C:\Users\junghwan.yoon\workspace\1.테스트\telegram-bot
pip install -r requirements.txt
```
- [ ] 설치 완료

### B-2. Telethon 최초 로그인
```bash
python scripts/login.py
```
진행 중 입력 요구사항:
1. **api_id** (A-3에서 기록한 숫자)
2. **api_hash** (A-3에서 기록한 문자열)
3. 내 **전화번호** (국가코드 포함, 예: `+821012345678`)
4. Telegram 앱으로 날아오는 **6자리 코드**
5. (2FA 설정되어 있다면) Telegram **2단계 비밀번호**

완료되면 화면에 **SESSION_STRING** 이 출력된다. 긴 base64 문자열을 복사·기록.

- [ ] SESSION_STRING 기록 완료

### B-3. 봇 DM chat_id 확인
먼저 A-2에서 만든 봇에게 Telegram 앱에서 임의 메시지(예: `hi`)를 1회 보낸 뒤:

```bash
python scripts/get_chat_id.py
```

내 사용자 chat_id(숫자)가 출력된다.

- [ ] BOT_CHAT_ID 기록 완료

### B-4. `.env` 파일 작성
```bash
cp .env.example .env
```
`.env` 열어서 A·B 단계에서 기록한 모든 값 입력.

- [ ] `.env` 모든 값 채움

### B-5. Dry-run 로컬 테스트
```bash
make dry-run
```
- 실제 채널을 Telethon으로 읽어서 stdout에 요약을 출력한다.
- DM은 보내지 않고, 상태(last_seen 등)도 갱신하지 않는다.
- [ ] 출력물 확인 (채널별 메시지 수, 요약, 출처 링크, 시세)
- 문제 있으면 로그 공유 후 Claude에게 수정 요청

### B-6. 실제 발송 1회 테스트
```bash
make run
```
- 내 Telegram에 DM이 도착하는지 확인.
- [ ] DM 도착, 포맷·링크·시세 이상 없음

---

## C. GitHub 저장소·자동화

### C-1. GitHub 저장소 생성
- [ ] GitHub 웹에서 **Private 저장소** 생성 (이름 예: `telegram-news-bot`)
- 저장소 초기화 옵션(README, .gitignore, license) 모두 **체크 해제**

### C-2. 원격 연결 및 첫 push
```bash
git remote add origin https://github.com/yjh8585/telegram-news-bot.git
git push -u origin master
```
- [ ] push 성공

### C-3. GitHub Secrets 등록
GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** 로 다음 6개 등록:

| Name | Value |
|---|---|
| `TG_API_ID` | A-3 api_id |
| `TG_API_HASH` | A-3 api_hash |
| `TG_SESSION_STRING` | B-2 SESSION_STRING |
| `BOT_TOKEN` | A-2 BOT_TOKEN |
| `BOT_CHAT_ID` | B-3 chat_id |
| `ANTHROPIC_API_KEY` | A-4 API Key |

- [ ] 6개 모두 등록

### C-4. Actions 수동 트리거로 검증
- GitHub 저장소 → **Actions** 탭 → `collect` 워크플로우 → **Run workflow** → `workflow_dispatch` 실행
- 로그 성공 / Telegram DM 도착 확인
- [ ] 수동 실행 성공

### C-5. cron-job.org 외부 스케줄러 설정 (GitHub cron 대체)

GitHub Actions 내장 cron은 수십 분 지연이 발생한다. cron-job.org 무료 서비스가
정각에 GitHub API를 호출해 워크플로우를 트리거하도록 설정한다.

#### C-5-1. GitHub PAT (Personal Access Token) 발급
- [ ] GitHub → 우측 상단 프로필 → **Settings**
- [ ] 좌측 하단 **Developer settings** → **Personal access tokens** → **Tokens (classic)**
- [ ] **Generate new token (classic)** 클릭
  - Note: `cron-job-dispatch`
  - Expiration: 원하는 기간 (1년 권장)
  - Scopes: **`workflow`** 체크박스 하나만 선택
- [ ] 생성된 토큰(`ghp_...`) 복사·보관 (다시 볼 수 없음)

#### C-5-2. cron-job.org 계정 생성
- [ ] https://cron-job.org 접속 → **Sign up** (무료)

#### C-5-3. 4개 Job 등록

아래 설정을 Job마다 반복한다. `{REPO_NAME}`은 실제 GitHub 저장소명으로 대체.

**공통 설정**
| 항목 | 값 |
|---|---|
| URL | `https://api.github.com/repos/yjh8585/{REPO_NAME}/actions/workflows/collect.yml/dispatches` |
| Request method | `POST` |
| Header 1 | `Authorization` : `Bearer {PAT 토큰}` |
| Header 2 | `Accept` : `application/vnd.github+json` |
| Header 3 | `Content-Type` : `application/json` |

> ⚠️ GitHub Actions 러너 큐잉 + 워크플로우 setup(pip·HuggingFace 캐시 등)에 평균 5~15분이
> 소요된다. 원하는 수신 시각보다 **15분 앞서** 트리거하도록 아래와 같이 설정한다.

**Job 1 — morning (KST 07:30 수신 목표)**
- Schedule: **매일 22:15 UTC** (= KST 07:15, 15분 선행)
- Request body:
  ```json
  {"ref": "master", "inputs": {"window": "morning", "dry_run": "false"}}
  ```

**Job 2 — late_morning (KST 11:00 수신 목표)**
- Schedule: **매일 01:45 UTC** (= KST 10:45, 15분 선행)
- Request body:
  ```json
  {"ref": "master", "inputs": {"window": "late_morning", "dry_run": "false"}}
  ```

**Job 3 — afternoon (KST 15:00 수신 목표)**
- Schedule: **매일 05:45 UTC** (= KST 14:45, 15분 선행)
- Request body:
  ```json
  {"ref": "master", "inputs": {"window": "afternoon", "dry_run": "false"}}
  ```

**Job 4 — evening (KST 18:00 수신 목표)**
- Schedule: **매일 08:45 UTC** (= KST 17:45, 15분 선행)
- Request body:
  ```json
  {"ref": "master", "inputs": {"window": "evening", "dry_run": "false"}}
  ```

- [ ] 4개 Job 모두 등록 완료

#### C-5-4. 동작 확인
- [ ] cron-job.org에서 Job 하나를 **수동 실행**(Save and run now)
- [ ] GitHub → Actions 탭에서 워크플로우가 `workflow_dispatch` 이벤트로 시작되는지 확인
- [ ] Telegram DM 도착 확인

#### C-5-5. 테스트런 (수동 실행 시 last_seen 보존)

cron-job.org **Run now**로 수동 테스트할 때는 Body에 `"no_commit": "true"`를
추가하면 **DM은 받되 last_seen은 갱신되지 않는다**. 이렇게 하면 정식 cron 시각에
실행될 때 같은 메시지가 다시 정상 수집된다.

**테스트런용 Body 예시 (window는 원하는 슬롯으로 변경):**
```json
{"ref": "master", "inputs": {"window": "evening", "dry_run": "false", "no_commit": "true"}}
```

**모드 비교**
| 옵션 | DM 발송 | last_seen 갱신 | 사용 시점 |
|---|---|---|---|
| 둘 다 false (기본) | ✅ | ✅ | 정식 cron 실행 |
| `no_commit: "true"` | ✅ | ❌ | 수동 테스트 (결과 확인용) |
| `dry_run: "true"`  | ❌ | ❌ | GitHub Actions 로그만으로 검증 |

#### C-5-6. 정기 점검 (월 1회 권장)

cron-job.org가 무단으로 Authorization 헤더를 비우거나 정책 변경으로 시크릿을
무효화하는 사례가 확인되었다. 26회 연속 실패 후 자동 비활성화될 때까지 기다리지
말고 월 1회 정상 동작을 직접 점검한다.

**점검 항목 (체크리스트)**
- [ ] cron-job.org 대시보드 접속 → 4개 Job 모두 **Enabled** 상태인지
- [ ] 4개 Job 각각 최근 실행이 `OK (204)`인지 (`Failed` 또는 `401/4xx` 없음)
- [ ] PAT(`cron-job-dispatch-v2`) 만료일 확인 — 만료 30일 전이면 새 토큰 발급 후 갈아끼우기
  - `https://github.com/settings/tokens` 에서 확인
- [ ] 최근 24시간 GitHub Actions 실행 결과 4개(morning / late_morning / afternoon / evening) 모두 `success`인지
  - 빠른 확인용 명령:
    ```bash
    gh api repos/yjh8585/telegram-bot/actions/workflows/collect.yml/runs \
      --jq '.workflow_runs[0:8] | .[] | {created_at, conclusion, display_title}'
    ```

**실패 알림 자동화 (강력 권장)**
cron-job.org Job별 설정 → **Notifications** → 실패 시 이메일 알림 ON.
26회 누적 대기 없이 1~3회 실패만에 즉시 인지 가능.

**401 발생 시 대처**
1. cron-job.org Headers 탭의 `Authorization` 값이 `Bearer ghp_...` 형식 그대로인지 확인
2. 값이 `Bearer`만 있고 토큰이 빠져있거나 비어 있으면 → 새 PAT 발급 후 4개 Job 헤더 모두 교체
   (cron-job.org가 시크릿 마스킹 동작으로 Save 시 값을 날려버리는 사례 있음)
3. PAT는 1Password 등 비밀번호 매니저에 저장해두면 복구 시 시간 절약

---

## C-6. 실행 간 중복 필터 검증 (배포·임계값 조정 시)

최근 발송 주제와 의미가 비슷한 새 글을 요약 전에 걸러 비용·반복을 줄이는 필터가
"진짜 새 소식"까지 지우지 않는지 실제 데이터로 확인한다. **Anthropic API 비용 없음**
(텔레그램 조회 + 로컬 임베딩만).

```bash
python -m scripts.validate_recent_dedup
```

- 출력: 최근 48h를 24h 경계로 나눠(memory / new), URL 제거 후 여러 임계값(0.80/0.85/0.90)의
  제거 건수와 0.85 상세 매칭(제거될 new ↔ 걸린 memory)을 보여준다.
- 판정: 상세 목록에서 **서로 다른 뉴스가 잘못 걸리면**(오탐) 임계값을 올린다.
  - `.env`에 `RECENT_DEDUP_THRESHOLD=0.90`(기본값) 유지 또는 상향.
  - 반대로 반복이 너무 안 걸러지면 `RECENT_DEDUP_THRESHOLD=0.85`로 하향해 관찰.
  - 기억 창은 `RECENT_DEDUP_WINDOW_HOURS`(기본 24)로 조정.
- 짧고 모호한 글은 임베딩상 스퍼리어스 유사도를 만들 수 있어, **운영은 원본이 아니라 토픽 요약**을
  기억으로 비교한다(이 스크립트의 원본 vs 원본 검증보다 안전).

- [ ] 검증 실행 후 오탐 없음 확인 (또는 임계값 조정)

---

## D. (선택) Shrimp Task Manager MCP 활성화

Claude Code 안에서 Shrimp 명령(`plan_task`, `split_tasks`, ...)을 쓰려면:

1. `.claude/settings.json` 은 이미 등록되어 있음 (확인: `cat .claude/settings.json`)
2. **Claude Code 재시작** 필요 (`/reload` 또는 창 재오픈)
3. 재시작 후 도구 목록에 `mcp__shrimp-task-manager__*` 가 나타나면 성공.

- [ ] Shrimp MCP 활성화 (선택)

---

## E. 트러블슈팅

### E-1. 봇이 계속 "분석 파이프라인 결과 없음" DM만 보낼 때
- **증상**: 정상 요약 대신 "분석 파이프라인 결과 없음 …" 에러 DM이 매 실행마다 옴. GitHub Actions 런도 전부 실패(failure).
- **1순위 원인 = Anthropic 크레딧(잔액) 소진.** Claude API가 `Your credit balance is too low to access the Anthropic API` (HTTP 400)를 반환하면 vision·summarize가 모두 실패해 토픽 0건 → 에러 DM이 발송된다.
  - 확인: `gh run view <실패한_run_id> --log | grep -i "credit balance"` — 위 문구가 보이면 크레딧 문제 확정.
  - 이 문구가 없고 대신 "JSON 파싱" 관련이면 Claude 응답 포맷 문제(별건).
- **복구 (당신이 직접)**: [Anthropic Console → Plans & Billing](https://console.anthropic.com/settings/billing) 에서 크레딧 충전. 다음 정각 실행부터 자동 복구(코드 배포 불필요).
- **재발 방지 (권장)**: 같은 화면에서 **자동 충전(Auto-reload)** 또는 **잔액 부족 알림(usage/billing alert)** 을 설정해 두면 조용히 바닥나는 걸 막을 수 있다.

---

## 진행 중 막히면

- 에러 메시지와 함께 Claude에게 공유 → 원인·해결책 제시받기.
- 민감 정보(토큰, 세션 문자열)는 절대 공유 금지. 필요하면 앞 4자리만 마스킹.
