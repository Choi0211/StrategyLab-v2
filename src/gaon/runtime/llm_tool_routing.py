"""Deterministic natural-language routing to safe read-only tools."""

from __future__ import annotations

import re


def route_read_only_tool(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized or _blocked(normalized):
        return None
    if _multi_symbol_research_execution(normalized):
        return "multi_symbol_research"
    if _explicit_multi_symbol_history_query(normalized):
        return "multi_symbol_research_history"
    if _explicit_multi_symbol_status_query(normalized):
        return "multi_symbol_research_status"
    if _multi_symbol_research_ascii(normalized):
        return "multi_symbol_research"
    if _autonomous_retest_execution_ascii(normalized):
        return "research_retest"
    if _research_retest_history(normalized):
        return "research_retest_history"
    if _research_retest_status(normalized):
        return "research_retest_status"
    if _autonomous_retest_ascii(normalized):
        return "research_retest"
    if _autonomous_retest(normalized):
        return "research_retest"
    if _krx_real_research(normalized):
        return "krx_real_research"
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


def _krx_real_research(value: str) -> bool:
    real_data = ("실제", "실데이터", "real", "yahoo", "krx", "삼성전자", "005930")
    research = ("백테스트", "backtest", "분석", "개선후보", "비교", "연구")
    return _contains_any(value, real_data) and _contains_any(value, research)


def _multi_symbol_research_ascii(value: str) -> bool:
    explicit_universe = (
        "여러종목",
        "다중종목",
        "복수종목",
        "모든종목",
        "모두",
        "종목들",
        "5개종목",
        "오개종목",
        "여러종목에서",
        "일반화",
        "universe",
        "multisymbol",
        "multi-symbol",
        "crosssymbol",
        "cross-symbol",
        "robustness",
    )
    symbols = {
        "삼성전자": ("삼성전자", "005930"),
        "sk하이닉스": ("sk하이닉스", "하이닉스", "000660"),
        "현대차": ("현대차", "005380"),
        "naver": ("naver", "035420"),
        "lg화학": ("lg화학", "051910"),
    }
    generalize = (
        "일반화",
        "여러종목",
        "모두검증",
        "모두",
        "검증",
        "검증해줘",
        "백테스트",
        "전략",
        "기록해줘",
        "연구해줘",
        "연구",
        "실제데이터",
        "실제",
        "realdata",
        "generalized",
        "generalization",
        "compare",
        "candidate",
        "tested",
        "robustness",
        "backtest",
    )
    code_count = len({token for token in re.findall(r"\d{6}", value) if token in {"005930", "000660", "005380", "035420", "051910"}})
    if not _contains_any(value, generalize):
        return False
    if code_count >= 2:
        return True
    if _contains_any(value, explicit_universe):
        return True
    mentioned = sum(1 for aliases in symbols.values() if _contains_any(value, aliases))
    return mentioned >= 2


def _multi_symbol_status(value: str) -> bool:
    return _explicit_multi_symbol_status_query(value)


def _multi_symbol_history(value: str) -> bool:
    return _explicit_multi_symbol_history_query(value)


def _multi_symbol_research_execution(value: str) -> bool:
    return _multi_symbol_research_ascii(value) and _contains_any(
        value,
        (
            "연구해줘",
            "검증해줘",
            "백테스트해줘",
            "비교해줘",
            "분석해줘",
            "판단해줘",
            "기록해줘",
            "research",
            "run",
            "execute",
            "backtest",
            "compare",
            "analyze",
        ),
    )


def _explicit_multi_symbol_status_query(value: str) -> bool:
    if not _contains_any(value, ("다중종목", "여러종목", "복수종목", "multisymbol", "multi-symbol")):
        return False
    status_terms = ("현재상태", "진행상태", "연구상태", "status")
    query_terms = ("보여줘", "알려줘", "조회", "확인", "show")
    return _contains_any(value, status_terms) and _contains_any(value, query_terms)


def _explicit_multi_symbol_history_query(value: str) -> bool:
    if not _contains_any(value, ("다중종목", "여러종목", "복수종목", "multisymbol", "multi-symbol", "researchhistory")):
        return False
    history_terms = (
        "연구이력",
        "연구기록",
        "이전연구",
        "지난연구",
        "과거연구",
        "저장된",
        "history",
        "historical",
    )
    query_terms = ("보여줘", "알려줘", "조회", "찾아", "확인", "show")
    return _contains_any(value, history_terms) and _contains_any(value, query_terms)


def _autonomous_retest(value: str) -> bool:
    retest = (
        "재검증",
        "다시검증",
        "자동재검증",
        "표본이부족",
        "충분한표본",
        "기간을확장",
        "기간확장",
        "더긴기간",
        "18개월",
        "3년",
        "5년",
        "충분한표본이나올때까지",
        "retest",
        "re-test",
        "expandperiod",
        "insufficientsample",
        "enoughsamples",
    )
    research = ("백테스트", "backtest", "검증", "연구", "분석", "삼성전자", "005930", "krx", "실제")
    return _contains_any(value, retest) and _contains_any(value, research)


def _research_retest_status(value: str) -> bool:
    return _contains_any(value, ("retest", "재검증", "표본", "기간확장", "샘플")) and _contains_any(value, ("상태", "status", "충분", "확인", "알려"))


def _research_retest_history(value: str) -> bool:
    return _contains_any(value, ("retest", "재검증", "기간확장", "검증과정", "lineage")) and _contains_any(value, ("이력", "history", "과정", "보여", "기록"))


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
    if _safe_boundary_negation(value):
        return False
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


def _safe_boundary_negation(value: str) -> bool:
    safety_terms = ("자동주문", "champion자동승격", "승인없는config변경", "승인없는", "nolivetrading", "noapprovalbypass", "nobroker", "nokis")
    negation_terms = ("하지말", "하지말고", "하지않", "금지", "없는", "no", "not", "without")
    return _contains_any(value, safety_terms) and _contains_any(value, negation_terms)


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


def _autonomous_retest_ascii(value: str) -> bool:
    retest = (
        "\uc7ac\uac80\uc99d",
        "\ub2e4\uc2dc\uac80\uc99d",
        "\uc790\ub3d9\uc7ac\uac80\uc99d",
        "\ud45c\ubcf8\uc774\ubd80\uc871",
        "\ucda9\ubd84\ud55c\ud45c\ubcf8",
        "\uae30\uac04\uc744\ud655\uc7a5",
        "\uae30\uac04\ud655\uc7a5",
        "\ub354\uae34\uae30\uac04",
        "18\uac1c\uc6d4",
        "3\ub144",
        "5\ub144",
        "\ucda9\ubd84\ud55c\ud45c\ubcf8\uc774\ub098\uc62c\ub54c\uae4c\uc9c0",
        "retest",
        "re-test",
        "expandperiod",
        "insufficientsample",
        "enoughsamples",
    )
    research = ("\ubc31\ud14c\uc2a4\ud2b8", "backtest", "\uac80\uc99d", "\uc5f0\uad6c", "\ubd84\uc11d", "\uc0bc\uc131\uc804\uc790", "005930", "krx", "\uc2e4\uc81c", "period", "samples")
    return _contains_any(value, retest) and _contains_any(value, research)


def _autonomous_retest_execution_ascii(value: str) -> bool:
    action = (
        "\ud574\uc918",
        "\uc9c4\ud589",
        "\ubc31\ud14c\uc2a4\ud2b8",
        "\ub2e4\uc2dc\ubc31\ud14c\uc2a4\ud2b8",
        "\ud655\uc7a5\ud574\uc11c",
        "\uae30\uac04\uc744\ud655\uc7a5",
        "\uc790\ub3d9\uc7ac\uac80\uc99d",
        "run",
        "execute",
        "backtest",
        "expand",
    )
    return _autonomous_retest_ascii(value) and _contains_any(value, action)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
