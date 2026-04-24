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
cd C:\Users\junghwan.yoon\workspace\telegram-bot
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

### C-5. Cron 자동 실행 확인
- 다음 예정 시각(07:30 / 11:00 / 15:00 / 18:00 KST) 중 하나에 자동 실행되는지 확인
- [ ] 자동 실행 성공

---

## D. (선택) Shrimp Task Manager MCP 활성화

Claude Code 안에서 Shrimp 명령(`plan_task`, `split_tasks`, ...)을 쓰려면:

1. `.claude/settings.json` 은 이미 등록되어 있음 (확인: `cat .claude/settings.json`)
2. **Claude Code 재시작** 필요 (`/reload` 또는 창 재오픈)
3. 재시작 후 도구 목록에 `mcp__shrimp-task-manager__*` 가 나타나면 성공.

- [ ] Shrimp MCP 활성화 (선택)

---

## 진행 중 막히면

- 에러 메시지와 함께 Claude에게 공유 → 원인·해결책 제시받기.
- 민감 정보(토큰, 세션 문자열)는 절대 공유 금지. 필요하면 앞 4자리만 마스킹.
