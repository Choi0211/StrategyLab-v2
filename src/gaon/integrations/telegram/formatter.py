"""Telegram formatting helpers."""

from __future__ import annotations


def escape_markdown(text: str) -> str:
    for char in "_*[]()~`>#+-=|{}.!\\":
        text = text.replace(char, f"\\{char}")
    return text


def split_message(text: str, limit: int = 4096) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    return tuple(text[index : index + limit] for index in range(0, len(text), limit)) or ("",)
