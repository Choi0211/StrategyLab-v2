"""Deterministic natural-language routing to safe read-only tools."""

from __future__ import annotations

import re


def route_read_only_tool(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized or _blocked(normalized):
        return None
    if _strategy_critique(normalized):
        return "strategy_critique"
    if _research_memory(normalized):
        return "research_memory_search"
    if _strategy_quality(normalized):
        return "strategy_quality_score"
    if _backtest(normalized):
        return "backtest_strategy"
    if _data_quality(normalized):
        return "data_quality_check"
    if _champion_status(normalized):
        return "champion_status"
    if _v5_pipeline_history(normalized):
        return "v5_pipeline_history"
    if _runtime_status(normalized):
        return "runtime_status"
    return None


def _strategy_critique(value: str) -> bool:
    critique = ("약점", "리스크", "위험", "문제", "비판", "평가", "취약", "과최적", "과최적화", "개선", "보완", "고쳐", "수정")
    strategy = ("전략", "strategy", "후보", "조건", "매매법")
    return _contains_any(value, strategy) and _contains_any(value, critique)


def _research_memory(value: str) -> bool:
    memory = ("비슷한", "유사", "지난연구", "이전연구", "연구했", "기억", "메모리", "memory", "저장된", "찾아")
    research = ("전략", "연구", "strategy", "research", "기록")
    return _contains_any(value, memory) and _contains_any(value, research)


def _strategy_quality(value: str) -> bool:
    return _contains_any(value, ("품질점수", "퀄리티", "quality", "score", "점수")) and _contains_any(value, ("전략", "strategy", "연구"))


def _backtest(value: str) -> bool:
    return _contains_any(value, ("백테스트", "backtest", "성과검증")) and not _contains_any(value, ("이력", "history"))


def _data_quality(value: str) -> bool:
    return _contains_any(value, ("데이터품질", "품질확인", "dataquality", "데이터검증"))


def _champion_status(value: str) -> bool:
    return (
        ("챔피언" in value and _contains_any(value, ("상태", "알려줘", "뭐야", "무엇", "현재", "지금")))
        or ("champion" in value and _contains_any(value, ("status", "상태", "show", "알려줘")))
    )


def _runtime_status(value: str) -> bool:
    return (
        (_contains_any(value, ("가온", "gaon", "runtime", "런타임", "서버")) and _contains_any(value, ("상태", "status", "알려줘")))
        or "gaonruntime상태" in value
    )


def _v5_pipeline_history(value: str) -> bool:
    return (
        (_contains_any(value, ("파이프라인", "pipeline")) and _contains_any(value, ("이력", "히스토리", "history", "기록", "실행")))
        or ("v5" in value and _contains_any(value, ("이력", "기록", "히스토리", "history")))
    )


def _blocked(value: str) -> bool:
    return _contains_any(
        value,
        (
            "명령실행",
            "실행해",
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
    )


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
