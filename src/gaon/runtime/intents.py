"""Rule-based conversation intent parsing."""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    GREETING = "greeting"
    CALL_GAON = "call_gaon"
    HELP = "help"
    STATUS = "status"
    TODAY_PLAN = "today_plan"
    MARKET_STATUS = "market_status"
    STOCK_ANALYSIS = "stock_analysis"
    SCHEDULE = "schedule"
    BACKTEST = "backtest"
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
    MULTI_SYMBOL_RESEARCH = "multi_symbol_research"
    SINGLE_SYMBOL_ANALYSIS = "single_symbol_analysis"
    COMPARE_SYMBOLS = "compare_symbols"
    MULTI_SYMBOL_ANALYSIS = "multi_symbol_analysis"
    EXPLAIN_PREVIOUS_RESULT = "explain_previous_result"
    SIMPLIFY_PREVIOUS_RESULT = "simplify_previous_result"
    SHOW_DETAILS = "show_details"
    STATUS_QUERY = "status_query"
    UNKNOWN = "unknown"


def parse_intent(text: str) -> Intent:
    normalized = text.strip().casefold()
    if not normalized:
        return Intent.UNKNOWN

    slash_intent = _parse_slash_intent(normalized)
    if slash_intent is not None:
        return slash_intent

    if normalized in {"안녕", "안녕하세요", "안녕 가온", "안녕하세요 가온"}:
        return Intent.GREETING
    if normalized in {"가온", "가온아", "gaon", "gaon아"}:
        return Intent.CALL_GAON
    if "도움말" in normalized or "뭘 할 수 있어" in normalized or "무엇을 할 수 있어" in normalized:
        return Intent.HELP

    # Specific task intents are checked before general status/plan intents.
    if "시장" in normalized and any(token in normalized for token in ("어때", "상태", "상황", "분위기")):
        return Intent.MARKET_STATUS
    try:
        from gaon.runtime.llm_tool_routing import _multi_symbol_research_execution, _normalize

        if _multi_symbol_research_execution(_normalize(normalized)):
            return Intent.MULTI_SYMBOL_RESEARCH
    except Exception:
        pass
    if any(token in normalized for token in ("분석해줘", "분석해 줘", "분석 부탁", "종목 분석")):
        return Intent.STOCK_ANALYSIS
    if "일정" in normalized and any(token in normalized for token in ("알려", "보여", "확인", "뭐")):
        return Intent.SCHEDULE
    if "백테스트" in normalized and any(token in normalized for token in ("돌려", "실행", "해줘", "해 줘")):
        return Intent.BACKTEST
    if any(token in normalized for token in ("지난 연구", "최근 연구", "연구 알려", "연구 내역")):
        return Intent.RECENT_RESEARCH
    if normalized.startswith("메모리 ") or "기억 찾아" in normalized or "기억 검색" in normalized:
        return Intent.SEARCH_MEMORY
    if "상태" in normalized and any(token in normalized for token in ("알려", "보여", "확인")):
        return Intent.STATUS
    if "오늘" in normalized and any(token in normalized for token in ("뭐부터", "계획", "할까", "해야")):
        return Intent.TODAY_PLAN
    return Intent.UNKNOWN


def _parse_slash_intent(normalized: str) -> Intent | None:
    if normalized in {"/help", "/start"}:
        return Intent.HELP
    if normalized == "/status":
        return Intent.STATUS
    if normalized == "/today":
        return Intent.TODAY_PLAN
    if normalized.startswith("/memory"):
        return Intent.SEARCH_MEMORY
    if normalized == "/research":
        return Intent.RESEARCH_STATUS
    if normalized == "/conflicts":
        return Intent.CONFLICTS
    if normalized == "/duplicates":
        return Intent.DUPLICATES
    if normalized == "/revalidate":
        return Intent.REVALIDATION_DUE
    if normalized == "/daily":
        return Intent.DAILY_REPORT
    if normalized == "/weekly":
        return Intent.WEEKLY_REVIEW
    if normalized in {"/notion-sync", "/notion_sync"}:
        return Intent.SYNC_NOTION
    if normalized == "/approvals":
        return Intent.APPROVAL_STATUS
    return None


def _parse_utf8_conversational_mvp(normalized: str) -> Intent | None:
    compact = normalized.replace(" ", "")
    if compact in {"안녕", "안녕하세요", "가온", "가온아", "hello", "hi", "gaon"}:
        return Intent.GREETING
    if any(token in normalized for token in ("도움말", "뭘 할 수", "무엇을 할 수", "help")):
        return Intent.HELP
    if any(token in normalized for token in ("자세히", "원본", "전체 결과", "상세")):
        return Intent.SHOW_DETAILS
    if any(token in normalized for token in ("쉽게", "간단히", "요약")):
        return Intent.SIMPLIFY_PREVIOUS_RESULT
    if any(token in normalized for token in ("왜", "그렇게 판단", "근거", "이유")):
        return Intent.EXPLAIN_PREVIOUS_RESULT
    symbol_count = _known_symbol_count(normalized)
    if symbol_count >= 2 and any(token in normalized for token in ("비교", "차이", "어느 쪽", "뭐가 더", "와", "랑", "하고")):
        return Intent.COMPARE_SYMBOLS
    if symbol_count == 1 and any(token in normalized for token in ("분석", "백테스트", "검증", "연구")):
        return Intent.SINGLE_SYMBOL_ANALYSIS
    if any(token in normalized for token in ("상태", "status", "런타임")):
        return Intent.STATUS_QUERY
    return None


def _known_symbol_count(normalized: str) -> int:
    aliases = (
        ("005930", "삼성전자", "삼성 전자"),
        ("000660", "sk하이닉스", "sk 하이닉스", "하이닉스"),
        ("005380", "현대차", "현대자동차"),
        ("035420", "naver", "네이버"),
        ("051910", "lg화학", "lg 화학"),
    )
    count = 0
    for group in aliases:
        if any(alias.casefold() in normalized for alias in group):
            count += 1
    return count
