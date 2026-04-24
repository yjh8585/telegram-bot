# 텔레그램 채널 요약 봇 개발 명령

.PHONY: install test lint format typecheck check-all run dry-run login chat-id clean

install:
	pip install -r requirements.txt

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests scripts

typecheck:
	mypy src

check-all: lint typecheck test

# 최신 window 자동 판정 후 실제 DM 전송 (주의)
run:
	python -m src.main --window auto

# 실제 Telethon 수집 + stdout 출력, DM 미발송, state 미갱신
dry-run:
	python -m src.main --window auto --dry-run

# Telethon 최초 로그인 → SESSION_STRING 발급
login:
	python scripts/login.py

# 봇 DM chat_id 확인
chat-id:
	python scripts/get_chat_id.py

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
