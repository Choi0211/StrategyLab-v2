"""Bounded deterministic natural-language routing to read-only tools."""

from __future__ import annotations

import re


def route_read_only_tool(text: str) -> str | None:
    value = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not value:
        return None
    if any(token in value for token in ("shell", "powershell", "cmd", "sql", "broker", "kis", "매수", "매도", "주문", "승인", "secret", "apikey")):
        return None
    if ("챔피언" in value or "champion" in value) and any(token in value for token in ("상태", "알려줘", "뭐야", "현재", "지금", "status", "show")):
        return "champion_status"
    if ("파이프라인" in value or "pipeline" in value or "v5" in value) and any(token in value for token in ("이력", "히스토리", "history", "기록", "실행")):
        return "v5_pipeline_history"
    if any(token in value for token in ("가온", "gaon", "runtime", "런타임", "서버")) and "상태" in value:
        return "runtime_status"
    return None
