"""Telegram MarkdownV2 메시지 빌더 + 4096자 제한 분할."""

from __future__ import annotations

from src.dtos import OutboundBlock, StockQuote
from src.window import Window

# Telegram MarkdownV2 예약 문자 — 모두 '\' 로 이스케이프해야 함.
_RESERVED = "_*[]()~`>#+-=|{}.!"
_TELEGRAM_LIMIT = 4000  # 실제 한도 4096, 여유분 96자
_IMPORTANCE_EMOJI: dict[str, str] = {"high": "🔴", "medium": "🟡", "low": "⚪"}


def escape_md(text: str) -> str:
    """MarkdownV2 예약 문자와 역슬래시를 모두 이스케이프."""
    out: list[str] = []
    for ch in text:
        if ch == "\\" or ch in _RESERVED:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _fmt_price(q: StockQuote) -> str:
    if q.currency == "KRW":
        return f"{int(round(q.price)):,}원"
    return f"${q.price:,.2f}"


def _fmt_change(q: StockQuote) -> str:
    if q.change_pct is None:
        return ""
    sign = "+" if q.change_pct >= 0 else ""
    return f"({sign}{q.change_pct:.1f}%)"


def _fmt_quote_line(q: StockQuote) -> str:
    name = q.name or q.code
    change = _fmt_change(q)
    base = f"• {name} ({q.code}): {_fmt_price(q)}"
    if change:
        base += f" {change}"
    return escape_md(base)


def _fmt_topic(index: int, block: OutboundBlock) -> str:
    topic = block.topic
    emoji = _IMPORTANCE_EMOJI.get(topic.importance, "🟡")
    title_line = f"*{escape_md(f'{emoji} {index}. {topic.title}')}*"
    lines: list[str] = [title_line, escape_md(topic.summary)]
    if block.quotes:
        lines.append("📈 *" + escape_md("시세") + "*")
        lines.extend(_fmt_quote_line(q) for q in block.quotes)
    if topic.sources:
        link_parts = [f"[{escape_md(s.channel_username)}]({s.url})" for s in topic.sources]
        lines.append("🔗 " + ", ".join(link_parts))
    return "\n".join(lines)


def _header(window: Window) -> str:
    return "📬 *" + escape_md(window.header_text) + "*"


def _empty_message(window: Window) -> str:
    return _header(window) + "\n\n" + escape_md("해당 구간에 수집된 새 정보가 없습니다.")


def build_messages(window: Window, blocks: list[OutboundBlock]) -> list[str]:
    """토픽 블록들을 MarkdownV2 텍스트로 만들고 _TELEGRAM_LIMIT 이내 여러 메시지로 분할."""
    if not blocks:
        return [_empty_message(window)]

    messages: list[str] = []
    current = _header(window)
    for idx, block in enumerate(blocks, start=1):
        topic_text = _fmt_topic(idx, block)
        candidate = current + "\n\n" + topic_text
        if len(candidate) > _TELEGRAM_LIMIT and current.strip():
            messages.append(current)
            current = topic_text
        else:
            current = candidate
    messages.append(current)
    return messages
