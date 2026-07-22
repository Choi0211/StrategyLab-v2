"""Telegram formatting helpers."""

from __future__ import annotations

TELEGRAM_TEXT_LIMIT = 4096
SAFE_TELEGRAM_CHUNK_LIMIT = 3900


def escape_markdown(text: str) -> str:
    for char in "_*[]()~`>#+-=|{}.!\\":
        text = text.replace(char, f"\\{char}")
    return text


def split_message(text: str, limit: int = SAFE_TELEGRAM_CHUNK_LIMIT) -> tuple[str, ...]:
    if limit < 1 or limit > TELEGRAM_TEXT_LIMIT:
        raise ValueError("limit must be positive")
    if limit <= 16:
        return tuple(text[index : index + limit] for index in range(0, len(text), limit)) or ("",)
    raw = _split_without_prefix(text, limit - 16)
    if len(raw) <= 1:
        return raw
    total = len(raw)
    chunks: list[str] = []
    for index, chunk in enumerate(raw, start=1):
        prefix = f"[{index}/{total}]\n"
        chunks.append(f"{prefix}{chunk}")
    return tuple(chunks)


def _split_without_prefix(text: str, limit: int) -> tuple[str, ...]:
    if not text:
        return ("",)
    remaining = text
    chunks: list[str] = []
    while len(remaining) > limit:
        cut = _best_cut(remaining, limit)
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    chunks.append(remaining)
    return tuple(chunks)


def _best_cut(text: str, limit: int) -> int:
    candidates = (
        text.rfind("\n\n", 0, limit + 1),
        text.rfind("\n", 0, limit + 1),
        max(text.rfind(". ", 0, limit + 1), text.rfind("? ", 0, limit + 1), text.rfind("! ", 0, limit + 1), text.rfind("다. ", 0, limit + 1)),
        text.rfind(" ", 0, limit + 1),
    )
    minimum = max(1, int(limit * 0.5))
    for candidate in candidates:
        if candidate >= minimum:
            return candidate + (2 if text[candidate : candidate + 2] in {". ", "? ", "! ", "다"} else 0)
    return limit
