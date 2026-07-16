"""Rule-based conversation intent parsing."""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    HELP = "help"
    STATUS = "status"
    TODAY_PLAN = "today_plan"
    RECENT_RESEARCH = "recent_research"
    SEARCH_MEMORY = "search_memory"
    RESEARCH_STATUS = "research_status"
    CONFLICTS = "conflicts"
    DUPLICATES = "duplicates"
    REVALIDATION_DUE = "revalidation_due"
    DAILY_REPORT = "daily_report"
    WEEKLY_REVIEW = "weekly_review"
    SYNC_NOTION = "sync_notion"
    APPROVAL_STATUS = "approval_status"
    UNKNOWN = "unknown"


def parse_intent(text: str) -> Intent:
    normalized = text.strip().casefold()
    if normalized in {"/help", "/start"}:
        return Intent.HELP
    if normalized == "/status" or "상황" in normalized:
        return Intent.STATUS
    if normalized == "/today" or "오늘" in normalized:
        return Intent.TODAY_PLAN
    if normalized.startswith("/memory") or "찾아" in normalized or "기억" in normalized:
        return Intent.SEARCH_MEMORY
    if normalized == "/research" or "연구" in normalized:
        return Intent.RESEARCH_STATUS
    if normalized == "/conflicts" or "충돌" in normalized:
        return Intent.CONFLICTS
    if normalized == "/duplicates" or "중복" in normalized:
        return Intent.DUPLICATES
    if normalized == "/revalidate" or "재검증" in normalized:
        return Intent.REVALIDATION_DUE
    if normalized == "/daily":
        return Intent.DAILY_REPORT
    if normalized == "/weekly":
        return Intent.WEEKLY_REVIEW
    if normalized in {"/notion-sync", "/notion_sync"} or "노션" in normalized:
        return Intent.SYNC_NOTION
    if normalized == "/approvals" or "승인" in normalized:
        return Intent.APPROVAL_STATUS
    return Intent.UNKNOWN
