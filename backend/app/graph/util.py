import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_time(value: str) -> float | None:
    """'hh:mm:ss' or 'mm:ss' -> seconds."""
    m = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})", value or "")
    if not m:
        return None
    h, mi, s = m.groups()
    return float(int(h or 0) * 3600 + int(mi) * 60 + int(s))


def yt_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


def text_of(content: Any) -> str:
    """Message content can be a string or a list of content blocks, depending on the model."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else part.get("text", "")
            for part in content
            if isinstance(part, (str, dict))
        )
    return str(content)


def last_ai_text(result: dict) -> str:
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and text_of(msg.content).strip():
            return text_of(msg.content).strip()
    return ""


def clean_tags(tags: list[str], limit: int = 4) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = re.sub(r"[^a-z0-9]", "", t.lower())
        if t and t not in out:
            out.append(t)
    return out[:limit]


def split_words(text: str, size: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)] or [""]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
