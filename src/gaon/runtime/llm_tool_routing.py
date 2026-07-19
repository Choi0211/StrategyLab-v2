"""Deterministic natural-language routing to safe read-only tools."""

from __future__ import annotations

import re


def route_read_only_tool(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if _contains_any(
        normalized,
        (
            "명령실행",
            "쉘실행",
            "shell",
            "cmd",
            "powershell",
            "sql",
            "broker",
            "kis",
            "매수",
            "매도",
            "주문",
            "승인",
            "자동배포",
            "secret",
            "apikey",
        ),
    ):
        return None
    if _champion_status(normalized):
        return "champion_status"
    if _v5_pipeline_history(normalized):
        return "v5_pipeline_history"
    if _runtime_status(normalized):
        return "runtime_status"
    return None


def _champion_status(value: str) -> bool:
    return (
        ("챔피언" in value and _contains_any(value, ("상태", "알려줘", "뭐야", "무엇", "현재", "지금")))
        or ("champion" in value and _contains_any(value, ("status", "상태", "show", "알려줘")))
    )


def _runtime_status(value: str) -> bool:
    return (
        (_contains_any(value, ("가온", "gaon", "runtime", "런타임", "서버")) and "상태" in value)
        or "gaonruntime상태" in value
    )


def _v5_pipeline_history(value: str) -> bool:
    return (
        (_contains_any(value, ("파이프라인", "pipeline")) and _contains_any(value, ("이력", "히스토리", "history", "기록", "실행")))
        or ("v5" in value and _contains_any(value, ("이력", "기록", "히스토리", "history")))
    )


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
