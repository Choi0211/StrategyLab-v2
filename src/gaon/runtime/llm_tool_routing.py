"""Deterministic natural-language routing to safe read-only tools."""

from __future__ import annotations

import re

from gaon.research.global_market import is_market_research_request, is_market_universe_request, resolve_market_scope

def route_read_only_tool(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if is_market_universe_request(text): return "multi_symbol_research"
    if _single_overseas_market_research(text): return "multi_symbol_research"
    if _krx_whole_market_research(normalized):
        return "multi_symbol_research"
    if _multi_symbol_research_utf8(normalized) and not _autonomous_learning_multi_symbol_override(normalized):
        return "multi_symbol_research"
    if _autonomous_retest_execution_ascii(normalized) and not _autonomous_learning_retest_override(normalized):
        return "research_retest"
    if _autonomous_learning_research_explicit(normalized) and not _blocked_autonomous_learning_request(normalized):
        return "autonomous_learning_research"
    if _blocked(normalized):
        return None
    if _autonomous_learning_research_explicit(normalized):
        return "autonomous_learning_research"
    if _multi_symbol_research_execution(normalized):
        return "multi_symbol_research"
    if _explicit_multi_symbol_history_query(normalized):
        return "multi_symbol_research_history"
    if _explicit_multi_symbol_status_query(normalized):
        return "multi_symbol_research_status"
    if _multi_symbol_research_utf8(normalized):
        return "multi_symbol_research"
    if _multi_symbol_research_ascii(normalized):
        return "multi_symbol_research"
    if _autonomous_learning_research_ascii(normalized):
        return "autonomous_learning_research"
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
    if _autonomous_research_cycle(normalized):
        return "autonomous_research_cycle"
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


def _autonomous_research_cycle(value: str) -> bool:
    autonomous = (
        "전략을검증",
        "전략검증",
        "검증해봐",
        "검증해줘",
        "추가검증",
        "표본이부족",
        "충분한표본",
        "근거가충분",
        "문제점을찾아",
        "약점을분석",
        "개선해",
        "계속연구",
        "다음검증",
        "무엇을배웠",
        "뭘배웠",
        "autonomousvalidate",
        "autonomouscritique",
        "continue研究",
        "retest",
        "researchcycle",
    )
    research = ("전략", "연구", "분석", "백테스트", "삼성전자", "005930", "krx", "strategy", "research", "validate")
    explicit = (
        "autonomousresearchcycle",
        "autonomouscycle",
        "autonomousvalidate",
        "autonomouscritique",
        "자율연구사이클",
        "자율검증사이클",
    )
    return _contains_any(value, explicit)


def _autonomous_learning_research_ascii(value: str) -> bool:
    if _autonomous_retest_ascii(value):
        return False
    memory_specific = ("비슷한", "유사", "지난연구", "이전연구", "연구했", "기억", "메모리", "memory", "저장된")
    if _contains_any(value, memory_specific):
        return False
    if _strategy_quality(value):
        return False
    v2_specific = (
        "처음부터다시연구",
        "처음부터다시연구해",
        "다시연구",
        "자료를찾아",
        "자료찾아",
        "연구자료를찾아",
        "외부연구자료",
        "외부연구",
        "근거자료",
        "외부자료",
        "지금까지배운",
        "지금까지배운내용",
        "배운내용",
        "개선전략후보",
        "전략후보",
        "후보전략",
        "가장좋은후보",
        "좋은전략후보",
        "후보가있",
        "승격승인",
        "승인을요청",
        "승인요청",
        "전략을만들어서검증",
        "전략을만들어검증",
        "autonomouslearning",
        "autonomousresearch",
        "externalresearch",
        "findevidence",
    )
    plain_v2_start = (
        "전략연구",
        "전략을연구",
        "전략연구해",
        "autonomousresearch",
        "autonomouslearning",
    )
    research = (
        "전략",
        "연구",
        "검증",
        "백테스트",
        "분석",
        "삼성전자",
        "005930",
        "krx",
        "실제",
        "시장데이터",
        "strategy",
        "research",
        "validate",
        "backtest",
    )
    if _contains_any(value, v2_specific) and _contains_any(value, research):
        return True
    if _contains_any(value, plain_v2_start) and not _contains_any(value, ("백테스트", "실제데이터", "실제시장데이터", "다중종목", "여러종목", "재검증", "검증해봐")):
        return True
    return False


def _single_overseas_market_research(text: str) -> bool:
    scope=resolve_market_scope(text)
    if scope is None or scope.market not in {"US","JP","HK","CN"}: return False
    if scope.universe_requested: return True
    if not is_market_research_request(text): return False
    if scope.market=="US": return bool(re.search(r"(?<![A-Za-z0-9])([A-Z]{1,5}(?:[.-][A-Z])?)(?![A-Za-z0-9])",text))
    return False


def _krx_whole_market_research(value: str) -> bool:
    scope = (
        "한국주식전체", "국내주식전체", "한국주식전종목", "국내주식전종목",
        "코스피코스닥", "코스피와코스닥", "코스피및코스닥",
        "kospikosdaq", "kospiandkosdaq", "krx전체", "krx전종목", "전체한국주식",
    )
    action = ("연구", "분석", "검증", "대상", "기준", "해주세요", "해줘", "research", "analyze", "validate")
    return _contains_any(value, scope) and _contains_any(value, action)


def _multi_symbol_research_ascii(value: str) -> bool:
    explicit_universe = (
        "여러종목",
        "다중종목",
        "복수종목",
        "모든종목",
        "한국주식전체",
        "국내주식전체",
        "한국주식전종목",
        "국내주식전종목",
        "코스피코스닥",
        "코스피와코스닥",
        "코스피및코스닥",
        "krx전체",
        "krx전종목",
        "미국주식전체", "미국주식전종목", "미국시장전체", "미장전체",
        "나스닥전체", "뉴욕증권거래소전체", "뉴욕거래소전체", "아멕스전체",
        "usstocks", "usmarket", "nasdaq", "nyse", "amex",
        "일본주식전체", "홍콩주식전체", "중국주식전체", "전세계주식", "글로벌주식",
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
        # "VPS 기반으로 구동되고 있나요?" is a structured runtime question.
        # It must use the read-only runtime probe rather than invite a
        # provider to invent deployment state.
        or ("vps" in value and _contains_any(value, ("구동", "동작", "상태", "연결", "가능")))
    )


def _v5_pipeline_history(value: str) -> bool:
    return (
        (_contains_any(value, ("파이프라인", "pipeline")) and _contains_any(value, ("이력", "히스토리", "history", "기록", "실행")))
        or ("v5" in value and _contains_any(value, ("이력", "기록", "히스토리", "history")))
    )


def _blocked(value: str) -> bool:
    if _autonomous_learning_research_ascii(value) and not _contains_any(value, ("매수", "매도", "주문", "broker", "kis", "shell", "cmd", "powershell", "sql")):
        return False
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


def _blocked_autonomous_learning_request(value: str) -> bool:
    return _contains_any(value, ("매수", "매도", "주문", "broker", "kis", "shell", "cmd", "powershell", "sql", "secret", "apikey"))


def _multi_symbol_research_utf8(value: str) -> bool:
    explicit_universe = (
        "다중종목",
        "여러종목",
        "복수종목",
        "모든종목",
        "대상종목",
        "5개종목",
        "각종목별",
        "종목별",
        "crosssymbol",
        "cross-symbol",
        "multisymbol",
        "multi-symbol",
    )
    execution = ("연구해줘", "검증해줘", "백테스트", "비교", "분석", "기록해줘", "판단해줘", "run", "execute", "validate", "compare")
    real_research = ("실제", "krx", "시장데이터", "백테스트", "전략", "연구", "candidate", "robustness")
    return _contains_any(value, explicit_universe) and _contains_any(value, execution) and _contains_any(value, real_research)


def _autonomous_learning_multi_symbol_override(value: str) -> bool:
    non_approval = (
        "외부자료",
        "외부연구",
        "외부연구자료",
        "자료를찾아",
        "자료를찾아서연구",
        "지금까지배운",
        "지금까지의연구기억",
        "연구기억",
        "처음부터다시연구",
        "다시연구",
        "autonomouslearning",
        "externalresearch",
        "promotioncandidate",
    )
    approval = ("승격승인", "승인요청", "승인직전")
    safety_negation = ("자동승격승인없는", "champion자동승격", "승인없는config", "승인없는")
    return _contains_any(value, non_approval) or (
        _contains_any(value, approval) and not _contains_any(value, safety_negation)
    )


def _autonomous_learning_retest_override(value: str) -> bool:
    return _contains_any(
        value,
        (
            "외부자료",
            "외부연구",
            "외부연구자료",
            "자료를찾아",
            "자료를찾아서연구",
            "지금까지배운",
            "지금까지의연구기억",
            "연구기억",
            "승격승인",
            "승인요청",
            "승인직전",
            "처음부터다시연구",
            "autonomouslearning",
            "externalresearch",
            "promotioncandidate",
        ),
    )


def _autonomous_learning_research_explicit(value: str) -> bool:
    if _strategy_quality(value):
        return False
    approval = (
        "승격승인",
        "승인요청",
        "승인요청하기전",
        "승인요청하기전까지",
        "승인직전",
        "좋은전략후보",
        "가장좋은후보",
        "promotioncandidate",
        "humanapproval",
    )
    external = (
        "외부자료",
        "외부연구",
        "외부연구자료",
        "자료를찾아",
        "자료찾아",
        "자료를찾아서연구",
        "연구자료",
        "근거자료",
        "externalresearch",
        "findevidence",
    )
    learning = (
        "지금까지배운",
        "지금까지배운내용",
        "배운내용",
        "학습내용",
        "지금까지의연구기억",
        "연구기억",
        "learningmemory",
    )
    improvement = (
        "처음부터다시연구",
        "다시연구",
        "문제점을찾",
        "약점을찾",
        "개선전략후보",
        "전략후보",
        "후보전략",
        "후보를만",
        "전략을만들어서검증",
        "전략을만들어검증",
        "strategycandidate",
    )
    robustness = (
        "oos",
        "outofsample",
        "워크포워드",
        "walkforward",
        "walk-forward",
        "시장국면",
        "레짐",
        "regime",
        "파라미터민감도",
        "거래비용",
        "transactioncost",
        "몬테카를로",
        "montecarlo",
        "monte-carlo",
        "robustness",
    )
    subject = (
        "삼성전자",
        "005930",
        "전략",
        "연구",
        "검증",
        "백테스트",
        "실제",
        "시장데이터",
        "krx",
        "strategy",
        "research",
        "validate",
        "backtest",
    )
    multi_symbol = _contains_any(value, ("다중종목", "여러종목", "복수종목", "모든종목", "5개종목", "crosssymbol", "cross-symbol", "multisymbol", "multi-symbol"))
    if multi_symbol and not _contains_any(value, external + learning + approval + ("처음부터다시연구", "다시연구", "자료를찾아서연구")):
        return False
    simple_memory_only = (
        _contains_any(value, ("비슷한", "유사", "지난연구", "이전연구", "저장된", "memory"))
        and not _contains_any(value, external + improvement + robustness + approval)
    )
    if simple_memory_only:
        return False
    v2_signals = external + learning + improvement + robustness + approval
    if _contains_any(value, v2_signals) and _contains_any(value, subject):
        return True
    if multi_symbol:
        return False
    return "개선" in value and "후보" in value and "검증" in value and "연구" in value


def _autonomous_retest_ascii(value: str) -> bool:
    retest = (
        "\uc7ac\uac80\uc99d",
        "\ub2e4\uc2dc\uac80\uc99d",
        "\uc790\ub3d9\uc7ac\uac80\uc99d",
        "\ub354\uac80\uc99d",
        "\uc804\ub7b5\uc744\ub354\uac80\uc99d",
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
