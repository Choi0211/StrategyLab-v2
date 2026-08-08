"""Deterministic conversational MVP helpers for Telegram-facing research chat."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re


class ConversationalMVPIntent(str, Enum):
    GREETING = "greeting"
    HELP = "help"
    SINGLE_SYMBOL_ANALYSIS = "single_symbol_analysis"
    COMPARE_SYMBOLS = "compare_symbols"
    MULTI_SYMBOL_ANALYSIS = "multi_symbol_analysis"
    EXPLAIN_PREVIOUS_RESULT = "explain_previous_result"
    SIMPLIFY_PREVIOUS_RESULT = "simplify_previous_result"
    PROFESSIONAL_EXPLANATION = "professional_explanation"
    SHOW_DETAILS = "show_details"
    INVESTMENT_DECISION_QUESTION = "investment_decision_question"
    RISK_QUESTION = "risk_question"
    STRATEGY_QUESTION = "strategy_question"
    TIMEFRAME_CHANGE_REQUEST = "timeframe_change_request"
    RERUN_REQUEST = "rerun_request"
    RECOMMENDATION_REQUEST = "recommendation_request"
    CONTEXTUAL_FOLLOWUP = "contextual_followup"
    STATUS_QUERY = "status_query"
    UNKNOWN = "unknown"


class ExplanationLevel(str, Enum):
    SIMPLE = "simple"
    STANDARD = "standard"
    PROFESSIONAL = "professional"
    DETAILED = "detailed"


class ConversationStyle(str, Enum):
    CONCISE = "concise"
    CONVERSATIONAL = "conversational"
    EXPLANATORY = "explanatory"
    TEACHING = "teaching"
    PROFESSIONAL = "professional"
    REPORT = "report"


class ExplanationDepth(str, Enum):
    SIMPLE = "simple"
    STANDARD = "standard"
    PROFESSIONAL = "professional"
    DETAILED = "detailed"


class ResponseLength(str, Enum):
    ONE_LINE = "one_line"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class PresentationFormat(str, Enum):
    PROSE = "prose"
    BULLETS = "bullets"
    TABLE = "table"


@dataclass(frozen=True)
class PresentationPreference:
    style: ConversationStyle = ConversationStyle.CONVERSATIONAL
    depth: ExplanationDepth = ExplanationDepth.STANDARD
    length: ResponseLength = ResponseLength.MEDIUM
    format: PresentationFormat = PresentationFormat.PROSE
    analogy_preference: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "style": self.style.value,
            "depth": self.depth.value,
            "length": self.length.value,
            "format": self.format.value,
            "analogy_preference": self.analogy_preference,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "PresentationPreference":
        try:
            return cls(
                style=ConversationStyle(str(payload.get("style", ConversationStyle.CONVERSATIONAL.value))),
                depth=ExplanationDepth(str(payload.get("depth", ExplanationDepth.STANDARD.value))),
                length=ResponseLength(str(payload.get("length", ResponseLength.MEDIUM.value))),
                format=PresentationFormat(str(payload.get("format", PresentationFormat.PROSE.value))),
                analogy_preference=bool(payload.get("analogy_preference", False)),
            )
        except ValueError:
            return cls()


@dataclass(frozen=True)
class Analogy:
    metric: str
    text: str


@dataclass(frozen=True)
class ExampleCalculation:
    label: str
    formula: str
    text: str


@dataclass(frozen=True)
class ConversationPresentationRequest:
    reasoning: "ConversationReasoningResult"
    user_text: str
    preference: PresentationPreference = PresentationPreference()


@dataclass(frozen=True)
class ConversationPresentationResult:
    style: ConversationStyle
    depth: ExplanationDepth
    length: ResponseLength
    format: PresentationFormat
    direct_answer: str
    explanation: str
    analogy: Analogy | None
    example: ExampleCalculation | None
    warnings: tuple[str, ...]
    next_action: str
    source_refs: tuple[str, ...]
    unsupported_claims_blocked: tuple[str, ...]


@dataclass(frozen=True)
class EvidencePoint:
    label: str
    value: str
    interpretation: str


@dataclass(frozen=True)
class Limitation:
    message: str


@dataclass(frozen=True)
class RiskPoint:
    message: str


@dataclass(frozen=True)
class NextAction:
    message: str


@dataclass(frozen=True)
class DecisionBoundary:
    can_answer: bool
    message: str


@dataclass(frozen=True)
class ConversationReasoningRequest:
    intent: ConversationalMVPIntent
    symbols: tuple[SymbolEntity, ...]
    user_text: str
    explanation_level: ExplanationLevel = ExplanationLevel.STANDARD


@dataclass(frozen=True)
class ConversationReasoningResult:
    intent: ConversationalMVPIntent
    symbols: tuple[str, ...]
    conclusion: str
    evidence_points: tuple[EvidencePoint, ...]
    limitations: tuple[Limitation, ...]
    risks: tuple[RiskPoint, ...]
    next_actions: tuple[NextAction, ...]
    explanation_level: ExplanationLevel
    source: str
    fixture_backed: bool
    quality_status: str
    confidence: str
    unsupported_claims_blocked: tuple[str, ...]
    decision_boundary: DecisionBoundary


@dataclass(frozen=True)
class SymbolEntity:
    symbol: str
    name: str


@dataclass(frozen=True)
class ConversationalRoute:
    intent: ConversationalMVPIntent
    symbols: tuple[SymbolEntity, ...]


@dataclass(frozen=True)
class ConversationalMVPContext:
    last_intent: str
    last_symbols: tuple[str, ...]
    last_result_kind: str
    last_research_result_ids: tuple[str, ...]
    last_rendered_result: str
    last_payloads: tuple[dict[str, object], ...]
    last_structured_results: tuple[dict[str, object], ...]
    last_summary: str
    last_detail_payload: dict[str, object]
    last_source: str
    last_fixture_backed: bool
    last_quality_status: str
    detail_level: str
    created_at: str
    updated_at: str


SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "005930": ("005930", "삼성전자", "삼성 전자", "samsung electronics", "samsung"),
    "000660": ("000660", "SK하이닉스", "SK 하이닉스", "sk하이닉스", "에스케이하이닉스", "하이닉스", "sk hynix", "hynix"),
    "005380": ("005380", "현대차", "현대자동차", "hyundai motor", "hyundai"),
    "035420": ("035420", "NAVER", "네이버", "naver"),
    "051910": ("051910", "LG화학", "LG 화학", "lg chem"),
}

SYMBOL_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "035420": "NAVER",
    "051910": "LG화학",
}

COMPARISON_TOKENS = ("비교", "차이", "어느 쪽", "뭐가 더", "대", "와", "과", " vs ", "versus", "compare")
ANALYSIS_TOKENS = ("분석", "백테스트", "검증", "연구", "어때", "봐줘", "알려줘", "analysis", "backtest")
MULTI_SYMBOL_TOKENS = ("여러 종목", "다종목", "전체 종목", "유니버스", "상위", "universe", "multi-symbol", "multisymbol")
DETAIL_TOKENS = ("자세히", "자세하게", "상세히", "상세하게", "원본", "전체 결과", "상세", "detail", "raw")
SIMPLIFY_TOKENS = ("쉽게", "쉽개", "간단히", "간단하게", "요약", "초등", "쉽게 설명", "simple")
EXPLAIN_TOKENS = ("왜", "이유", "판단", "판간", "근거", "그렇게", "그절", "그런", "explain")
STATUS_TOKENS = ("상태", "status", "정상", "하고 있어")
PROFESSIONAL_TOKENS = ("전문적으로", "전문가처럼", "전문 설명", "professional", "technical")
INVESTMENT_DECISION_TOKENS = ("지금 사도", "매수해도", "사도 돼", "사야", "팔아야", "매도해야", "buy now", "should buy", "sell now")
RISK_TOKENS = ("위험", "리스크", "손실", "mdd", "낙폭", "risk", "drawdown")
STRATEGY_TOKENS = ("전략", "조건", "진입", "청산", "손절", "strategy", "entry", "exit")
TIMEFRAME_TOKENS = ("기간", "3년", "5년", "18개월", "6개월", "더 긴", "longer period", "timeframe")
RERUN_TOKENS = ("다시 분석", "다시 검증", "다시 해", "재검증", "최신 데이터", "조건을 바꿔", "rerun", "re-run", "retest")
RECOMMENDATION_TOKENS = ("추천", "권해", "좋아", "유리", "recommend", "recommendation")
CONTEXTUAL_TOKENS = ("그럼", "그러면", "반도체 중에서는", "그 종목", "그 전략", "then", "what about")

PRESENTATION_STYLE_TOKENS = (
    "\ud55c \uc904",
    "\uc9e7\uac8c",
    "\uac04\ub2e8\ud788",
    "\uac04\ub2e8\ud558\uac8c",
    "\uc790\uc5f0\uc2a4\ub7fd\uac8c",
    "\uc774\ud574\ud558\uae30 \uc27d\uac8c",
    "\uac00\ub974\uccd0\uc8fc\ub4ef",
    "\ube44\uc720",
    "\uc608\ub97c \ub4e4\uc5b4",
    "\ucd08\ubcf4\uc790",
    "\uc544\uc774\uc5d0\uac8c",
    "\ubcf4\uace0\uc11c",
    "\ud45c\ub85c",
    "\uc804\ubb38\uc6a9\uc5b4 \ube7c",
    "\uc870\uae08 \ub354 \uc790\uc138",
    "\uc544\uc8fc \uc790\uc138",
)

RATIO_METRICS = frozenset({"total_return", "cagr", "mdd", "win_rate", "exposure"})
CURRENCY_METRICS = frozenset({"average_trade", "average_win", "average_loss", "expectancy", "ending_equity", "initial_capital"})
COUNT_METRICS = frozenset({"trade_count", "longest_losing_streak"})
DIMENSIONLESS_METRICS = frozenset({"sharpe", "profit_factor", "payoff_ratio"})

_EXPLAIN_ALIASES = (
    "왜 그렇게 판단했어",
    "왜 그렇게 판단한 거야",
    "왜 그런 판단을 했어",
    "왜 그절 판단했어",
    "왜 그렇게 판간했어",
    "왜 그절 판간했어",
    "이유가 뭐야",
    "왜 그런 거야",
)
_SIMPLIFY_ALIASES = (
    "쉽게 설명해줘",
    "쉽게설명해줘",
    "쉽게 알려줘",
    "쉽게 말해줘",
    "간단히 설명해줘",
    "간단하게 말해줘",
    "쉽개 설명해줘",
)
_DETAIL_ALIASES = (
    "자세히 보여줘",
    "자세하게 보여줘",
    "상세히 보여줘",
    "전체 내용 보여줘",
    "자세한 결과 보여줘",
    "원본 결과 보여줘",
)


def extract_symbol_entities(text: str) -> tuple[SymbolEntity, ...]:
    normalized = text.casefold()
    found: list[SymbolEntity] = []
    for token in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        if token in SYMBOL_NAMES and token not in [item.symbol for item in found]:
            found.append(SymbolEntity(token, SYMBOL_NAMES[token]))
    for symbol, aliases in SYMBOL_ALIASES.items():
        if symbol in [item.symbol for item in found]:
            continue
        if any(alias.casefold() in normalized for alias in aliases):
            found.append(SymbolEntity(symbol, SYMBOL_NAMES[symbol]))
    return tuple(found)


def classify_conversational_route(text: str) -> ConversationalRoute:
    normalized = text.strip().casefold()
    symbols = extract_symbol_entities(text)
    if not normalized:
        return ConversationalRoute(ConversationalMVPIntent.UNKNOWN, ())
    typo_followup = _classify_followup_typo(normalized)
    if typo_followup is not None:
        return ConversationalRoute(typo_followup, symbols)
    if _is_simple_greeting(normalized):
        return ConversationalRoute(ConversationalMVPIntent.GREETING, ())
    if any(token in normalized for token in ("도움말", "뭘 할 수", "무엇을 할 수", "help", "/help", "/start")):
        return ConversationalRoute(ConversationalMVPIntent.HELP, symbols)
    if any(token in normalized for token in PRESENTATION_STYLE_TOKENS):
        if any(token in normalized for token in ("\ubcf4\uace0\uc11c", "\ud45c\ub85c", "\uc790\uc138", "\uc0c1\uc138")):
            return ConversationalRoute(ConversationalMVPIntent.SHOW_DETAILS, symbols)
        return ConversationalRoute(ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, symbols)
    if any(token in normalized for token in DETAIL_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.SHOW_DETAILS, symbols)
    if any(token in normalized for token in SIMPLIFY_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT, symbols)
    if any(token in normalized for token in PROFESSIONAL_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.PROFESSIONAL_EXPLANATION, symbols)
    if any(token in normalized for token in INVESTMENT_DECISION_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, symbols)
    if any(token in normalized for token in TIMEFRAME_TOKENS) and any(token in normalized for token in ("다시", "해줘", "검증", "분석", "돌려", "rerun", "retest")):
        return ConversationalRoute(ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST, symbols)
    if any(token in normalized for token in RERUN_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.RERUN_REQUEST, symbols)
    if any(token in normalized for token in RISK_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.RISK_QUESTION, symbols)
    if any(token in normalized for token in STRATEGY_TOKENS) and not any(token in normalized for token in ANALYSIS_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.STRATEGY_QUESTION, symbols)
    if any(token in normalized for token in RECOMMENDATION_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.RECOMMENDATION_REQUEST, symbols)
    if any(token in normalized for token in CONTEXTUAL_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, symbols)
    if any(token in normalized for token in EXPLAIN_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT, symbols)
    if len(symbols) >= 2 and any(token in normalized for token in COMPARISON_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.COMPARE_SYMBOLS, symbols)
    if any(token in normalized for token in MULTI_SYMBOL_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.MULTI_SYMBOL_ANALYSIS, symbols)
    if len(symbols) == 1 and any(token in normalized for token in ANALYSIS_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS, symbols)
    if any(token in normalized for token in STATUS_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.STATUS_QUERY, symbols)
    return ConversationalRoute(ConversationalMVPIntent.UNKNOWN, symbols)


def render_greeting() -> str:
    return "안녕하세요, 영하님. 영하님의 AI 연구 파트너 가온입니다. 무엇을 함께 살펴볼까요?"


def render_help() -> str:
    return "\n".join(
        [
            "영하님, 지금은 다음 요청을 안전하게 지원할 수 있습니다.",
            "- 삼성전자 분석해줘",
            "- 삼성전자와 SK하이닉스 비교해줘",
            "- 왜 그렇게 판단했어?",
            "- 쉽게 설명해줘",
            "- 자세히 보여줘",
            "주문, 자동 승인, Champion 자동 승격은 수행하지 않습니다.",
        ]
    )


def render_unknown(symbols: tuple[SymbolEntity, ...] = ()) -> str:
    if symbols:
        names = ", ".join(f"{item.name}({item.symbol})" for item in symbols)
        return f"영하님, {names}은 인식했지만 요청 의도를 정확히 판단하지 못했습니다. '분석해줘' 또는 '비교해줘'처럼 말씀해 주세요."
    return "죄송하지만 요청을 정확히 이해하지 못했습니다, 영하님. '삼성전자 분석해줘', '삼성전자와 SK하이닉스 비교해줘'처럼 말씀해 주세요."


def render_status() -> str:
    return "가온은 현재 응답 가능합니다, 영하님. 다만 실제 연구는 데이터 품질 검증과 safe tool 경계를 통과한 결과만 말씀드립니다."


def render_missing_context() -> str:
    return "직전에 설명할 분석 결과가 없습니다. 먼저 종목 분석이나 비교를 요청해 주세요."


def render_single_symbol_summary(payload: dict[str, object], *, user_text: str, detail_level: str = "summary") -> str:
    symbol = _symbol_from_payload(payload)
    name = SYMBOL_NAMES.get(symbol, symbol)
    dataset = _dict(payload.get("dataset"))
    metadata = _dict(dataset.get("metadata"))
    quality = _dict(payload.get("quality"))
    backtest = _dict(payload.get("backtest"))
    metrics = _dict(backtest.get("metrics"))
    strategy = _dict(payload.get("strategy"))
    warnings = _reliability_warnings(payload)
    lines = [
        f"영하님, {name}({symbol}) 실제 시장 데이터를 사용한 백테스트 결과입니다.",
        "",
        "[분석 대상과 데이터 기간]",
        f"- 종목: {name}({symbol})",
        f"- 기간: {metadata.get('start_date', 'unknown')} ~ {metadata.get('end_date', 'unknown')}",
        f"- 데이터: {_source_label(metadata)}",
        "",
        "[한 줄 결론]",
        _one_line_conclusion(metrics),
    ]
    if warnings:
        lines.extend(["", "[신뢰도 주의]", *[f"- {warning}" for warning in warnings]])
    lines.extend(
        [
            "",
            "[주요 결과]",
            f"- 총 수익률: {_format_percent(metrics.get('total_return'))}",
            f"- MDD: {_format_percent(metrics.get('mdd'))}",
            f"- 거래 수: {_format_int(metrics.get('trade_count'))}회",
            f"- Profit Factor: {_format_profit_factor(metrics.get('profit_factor'), metrics.get('trade_count'))}",
            f"- 승률: {_format_percent(metrics.get('win_rate'))}",
            "",
            "[데이터 신뢰도]",
            f"- {_quality_label(quality.get('status'))}",
            f"- {_source_label(metadata)}",
            "",
            "[주요 위험]",
            *[f"- {item}" for item in _risk_lines(payload)],
            "",
            "[다음 가능한 작업]",
            "- 표본이 부족하면 자동 재검증으로 기간을 확장할 수 있습니다.",
            "- 다른 종목과 같은 조건으로 비교할 수 있습니다.",
        ]
    )
    if detail_level == "detail":
        lines.extend(["", "[상세 결과]", *_detail_lines(payload, strategy, metrics)])
    return _sanitize_final("\n".join(lines))


def render_symbol_comparison(payloads: tuple[dict[str, object], ...], *, user_text: str) -> str:
    failures = [payload for payload in payloads if payload.get("status") == "failure"]
    if failures:
        failed = ", ".join(str(item.get("symbol", "unknown")) for item in failures)
        return f"영하님, 일부 종목 연구가 실패했습니다: {failed}. 성공한 종목만으로 우열을 만들지 않겠습니다."
    rows = []
    for payload in payloads:
        symbol = _symbol_from_payload(payload)
        metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
        quality = _dict(payload.get("quality"))
        rows.append((symbol, SYMBOL_NAMES.get(symbol, symbol), metrics, quality, _reliability_warnings(payload)))
    lines = [
        "영하님, 요청하신 종목들을 동일 조건으로 비교했습니다.",
        "- 조건: 같은 전략 문장, 같은 기본 수수료/슬리피지/세금 가정, 같은 체결 규칙을 사용했습니다.",
        "",
        "[비교 결과]",
    ]
    for symbol, name, metrics, quality, warnings in rows:
        confidence = "낮음" if warnings else "보통"
        lines.append(
            f"- {name}({symbol}): 총 수익률 {_format_percent(metrics.get('total_return'))}, "
            f"MDD {_format_percent(metrics.get('mdd'))}, 거래 수 {_format_int(metrics.get('trade_count'))}회, "
            f"{_confidence_label(confidence)}, {_quality_label(quality.get('status'))}"
        )
    lines.extend(["", "[판단]", _comparison_conclusion(rows), "", "[주의]"])
    lines.extend(f"- {warning}" for _, _, _, _, warnings in rows for warning in warnings)
    if not any(warnings for _, _, _, _, warnings in rows):
        lines.append("- 모든 결론은 구조화된 백테스트 결과 안에서만 해석했습니다.")
    return _sanitize_final("\n".join(lines))


def render_follow_up(context: ConversationalMVPContext, intent: ConversationalMVPIntent, *, user_text: str = "", preference: PresentationPreference | None = None) -> str:
    payloads = context.last_structured_results or context.last_payloads
    if intent in {
        ConversationalMVPIntent.PROFESSIONAL_EXPLANATION,
        ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION,
        ConversationalMVPIntent.RISK_QUESTION,
        ConversationalMVPIntent.STRATEGY_QUESTION,
        ConversationalMVPIntent.RECOMMENDATION_REQUEST,
        ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
        ConversationalMVPIntent.SHOW_DETAILS,
        ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT,
    }:
        if context.last_result_kind == "symbol_comparison" and payloads:
            normalized = user_text.casefold()
            if intent is ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT:
                return render_symbol_comparison_simple(payloads)
            if intent is ConversationalMVPIntent.SHOW_DETAILS and "\ud45c\ub85c" not in normalized:
                return render_symbol_comparison_detail(payloads)
            if intent is ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT or "??" in user_text:
                return render_symbol_comparison_explanation(payloads, context)
        if payloads:
            pref = presentation_preference_for_text(user_text, preference)
            if intent is ConversationalMVPIntent.PROFESSIONAL_EXPLANATION:
                pref = PresentationPreference(style=ConversationStyle.PROFESSIONAL, depth=ExplanationDepth.PROFESSIONAL, length=pref.length, format=pref.format, analogy_preference=pref.analogy_preference)
            elif intent is ConversationalMVPIntent.SHOW_DETAILS and pref.style is ConversationStyle.CONVERSATIONAL:
                pref = PresentationPreference(style=ConversationStyle.REPORT, depth=ExplanationDepth.DETAILED, length=ResponseLength.LONG, format=PresentationFormat.BULLETS, analogy_preference=pref.analogy_preference)
            elif intent is ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT and pref.style is ConversationStyle.CONVERSATIONAL:
                pref = PresentationPreference(style=ConversationStyle.EXPLANATORY, depth=ExplanationDepth.SIMPLE, length=ResponseLength.SHORT, format=PresentationFormat.PROSE, analogy_preference=pref.analogy_preference)
            return render_presentation_from_payloads(payloads, intent=intent, user_text=user_text, preference=pref)
        return _sanitize_final(context.last_summary or context.last_rendered_result)
    if intent in {ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST, ConversationalMVPIntent.RERUN_REQUEST}:
        return render_rerun_boundary(context, intent)
    if context.last_result_kind == "symbol_comparison" and payloads:
        return render_symbol_comparison_explanation(payloads, context)
    if payloads:
        return render_single_symbol_explanation(payloads[0], context)
    return _sanitize_final(context.last_summary or context.last_rendered_result)

def explanation_level_for_text(text: str, intent: ConversationalMVPIntent) -> ExplanationLevel:
    normalized = text.casefold()
    if intent is ConversationalMVPIntent.SHOW_DETAILS or any(token in normalized for token in DETAIL_TOKENS):
        return ExplanationLevel.DETAILED
    if intent is ConversationalMVPIntent.PROFESSIONAL_EXPLANATION or any(token in normalized for token in PROFESSIONAL_TOKENS):
        return ExplanationLevel.PROFESSIONAL
    if intent is ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT or any(token in normalized for token in SIMPLIFY_TOKENS):
        return ExplanationLevel.SIMPLE
    return ExplanationLevel.STANDARD


def render_reasoning_from_payloads(payloads: tuple[dict[str, object], ...], *, intent: ConversationalMVPIntent, level: ExplanationLevel, user_text: str) -> str:
    result = build_reasoning_result(payloads, intent=intent, level=level, user_text=user_text)
    return render_reasoning_result(result)


def build_reasoning_result(payloads: tuple[dict[str, object], ...], *, intent: ConversationalMVPIntent, level: ExplanationLevel, user_text: str) -> ConversationReasoningResult:
    if not payloads:
        return ConversationReasoningResult(
            intent,
            (),
            "직전에 설명할 연구 결과가 없습니다.",
            (),
            (Limitation("먼저 종목 분석이나 비교를 실행해야 합니다."),),
            (),
            (NextAction("분석할 종목과 전략 조건을 다시 알려 주세요."),),
            level,
            "unknown",
            False,
            "unknown",
            "판단 보류",
            ("no_prior_research_context",),
            DecisionBoundary(False, "근거가 없어 판단하지 않습니다."),
        )
    symbols = tuple(_symbol_from_payload(payload) for payload in payloads)
    first_metadata = _dict(_dict(payloads[0].get("dataset")).get("metadata"))
    source = _source_label(first_metadata)
    fixture_backed = any(_dict(_dict(payload.get("dataset")).get("metadata")).get("fixture_backed") is True for payload in payloads)
    quality_statuses = tuple(str(_dict(payload.get("quality")).get("status", "unknown")) for payload in payloads)
    confidence = _reasoning_confidence(payloads)
    evidence = tuple(point for payload in payloads for point in _reasoning_evidence_points(payload))
    limitations = tuple(dict.fromkeys(limitation for payload in payloads for limitation in _reasoning_limitations(payload, intent)))
    risks = tuple(dict.fromkeys(risk for payload in payloads for risk in _reasoning_risks(payload)))
    next_actions = tuple(dict.fromkeys(action for payload in payloads for action in _reasoning_next_actions(payload, intent)))
    blocked = _blocked_claims(intent)
    boundary = _decision_boundary(intent, payloads)
    return ConversationReasoningResult(
        intent=intent,
        symbols=symbols,
        conclusion=_reasoning_conclusion(intent, payloads),
        evidence_points=evidence,
        limitations=tuple(Limitation(item) for item in limitations),
        risks=tuple(RiskPoint(item) for item in risks),
        next_actions=tuple(NextAction(item) for item in next_actions),
        explanation_level=level,
        source=source,
        fixture_backed=fixture_backed,
        quality_status=",".join(dict.fromkeys(quality_statuses)),
        confidence=confidence,
        unsupported_claims_blocked=blocked,
        decision_boundary=boundary,
    )


def render_reasoning_result(result: ConversationReasoningResult) -> str:
    if result.explanation_level is ExplanationLevel.SIMPLE:
        lines = [
            f"[결론] {result.conclusion}",
            f"[이유] {result.evidence_points[0].interpretation if result.evidence_points else '구조화된 근거가 부족합니다.'}",
            f"[한계] {result.limitations[0].message if result.limitations else result.decision_boundary.message}",
            f"[다음 단계] {result.next_actions[0].message if result.next_actions else '추가 검증 후 다시 판단해야 합니다.'}",
        ]
        return _sanitize_final("\n".join(lines))
    lines = [
        "[결론]",
        f"- {result.conclusion}",
        "",
        "[핵심 근거]",
    ]
    for point in result.evidence_points[: _reasoning_limit(result.explanation_level, default=4)]:
        lines.append(f"- {point.label}: {point.value}. {point.interpretation}")
    lines.extend(["", "[주의할 점]"])
    for limitation in result.limitations[: _reasoning_limit(result.explanation_level, default=4)]:
        lines.append(f"- {limitation.message}")
    if result.risks:
        lines.extend(["", "[위험]", *[f"- {risk.message}" for risk in result.risks[: _reasoning_limit(result.explanation_level, default=4)]]])
    if result.explanation_level in {ExplanationLevel.PROFESSIONAL, ExplanationLevel.DETAILED}:
        lines.extend(
            [
                "",
                "[전문 지표 해석]",
                "- MDD는 백테스트 중 고점 대비 최대 자산 감소 폭입니다.",
                "- Sharpe는 위험 대비 수익률 지표이지만, 거래 표본이 적으면 신뢰도 있게 해석하기 어렵습니다.",
                "- Profit Factor는 총이익 대비 총손실 비율이며, 손실 거래가 없으면 강한 근거가 아니라 해석 제한으로 봅니다.",
                "- Exposure는 시장에 투자되어 있던 기간의 비율입니다.",
                "- trade_count는 실제로 발생한 거래 수이며, 표본 신뢰도를 판단하는 핵심 입력입니다.",
            ]
        )
    lines.extend(["", "[현재 결과로 말할 수 없는 것]"])
    for claim in result.unsupported_claims_blocked:
        lines.append(f"- {claim}")
    lines.extend(["", "[다음 검증 또는 가능한 행동]"])
    for action in result.next_actions[: _reasoning_limit(result.explanation_level, default=4)]:
        lines.append(f"- {action.message}")
    return _sanitize_final("\n".join(lines))




def presentation_preference_for_text(text: str, existing: PresentationPreference | None = None) -> PresentationPreference:
    normalized = text.casefold()
    base = existing or PresentationPreference()
    style = base.style
    depth = base.depth
    length = base.length
    analogy = base.analogy_preference
    original_style = style
    explicit_length = any(token in normalized for token in ("\ud55c \uc904", "1\uc904", "\uc9e7\uac8c", "\uac04\ub2e8\ud788", "\uac04\ub2e8\ud558\uac8c", "\uc870\uae08 \ub354 \uc790\uc138", "\uc544\uc8fc \uc790\uc138", "\uc790\uc138\ud788", "\uc0c1\uc138\ud788"))
    if any(token in normalized for token in ("\ud55c \uc904", "\uc9e7\uac8c", "\uac04\ub2e8\ud788", "\uac04\ub2e8\ud558\uac8c")):
        style = ConversationStyle.CONCISE
    elif any(token in normalized for token in ("\uc790\uc5f0\uc2a4\ub7fd\uac8c", "\ub300\ud654\ucc98\ub7fc")):
        style = ConversationStyle.CONVERSATIONAL
    elif any(token in normalized for token in ("\uc774\ud574\ud558\uae30 \uc27d\uac8c", "\uc804\ubb38\uc6a9\uc5b4 \ube7c", "\uc26c\uc6b4 \ud45c\ud604")):
        style = ConversationStyle.EXPLANATORY
        depth = ExplanationDepth.SIMPLE
    elif any(token in normalized for token in ("\uac00\ub974\uccd0\uc8fc\ub4ef", "\ucd08\ubcf4\uc790", "\uc544\uc774\uc5d0\uac8c")):
        style = ConversationStyle.TEACHING
        depth = ExplanationDepth.SIMPLE
    elif any(token in normalized for token in ("\uc804\ubb38\uc801\uc73c\ub85c", "\uc804\ubb38\uac00\ucc98\ub7fc", "\uc804\ubb38 \uc124\uba85")):
        style = ConversationStyle.PROFESSIONAL
        depth = ExplanationDepth.PROFESSIONAL
    elif any(token in normalized for token in ("\ubcf4\uace0\uc11c", "\ub9ac\ud3ec\ud2b8")):
        style = ConversationStyle.REPORT
        depth = ExplanationDepth.DETAILED
    if "\ube44\uc720" in normalized:
        style = ConversationStyle.TEACHING
        analogy = True
    if "\uc608\ub97c \ub4e4\uc5b4" in normalized:
        style = ConversationStyle.TEACHING
    if "\ud45c\ub85c" in normalized:
        style = ConversationStyle.REPORT
        depth = ExplanationDepth.DETAILED
    if any(token in normalized for token in ("\ud55c \uc904", "1\uc904")):
        length = ResponseLength.ONE_LINE
    elif any(token in normalized for token in ("\uc9e7\uac8c", "\uac04\ub2e8\ud788", "\uac04\ub2e8\ud558\uac8c")):
        length = ResponseLength.SHORT
    elif "\uc870\uae08 \ub354 \uc790\uc138" in normalized:
        length = ResponseLength.MEDIUM
    elif any(token in normalized for token in ("\uc544\uc8fc \uc790\uc138", "\uc790\uc138\ud788", "\uc0c1\uc138\ud788")):
        length = ResponseLength.LONG
    if any(token in normalized for token in ("\uc27d\uac8c", "\uc26c\uc6b4", "\ucd08\ubcf4\uc790", "\uc804\ubb38\uc6a9\uc5b4 \ube7c")):
        depth = ExplanationDepth.SIMPLE
    elif any(token in normalized for token in ("\uc804\ubb38\uc801\uc73c\ub85c", "\uc804\ubb38\uac00")):
        depth = ExplanationDepth.PROFESSIONAL
    elif any(token in normalized for token in ("\uc790\uc138\ud788", "\uc0c1\uc138\ud788", "\ubcf4\uace0\uc11c")):
        depth = ExplanationDepth.DETAILED
    format = base.format
    if "\ud45c\ub85c" in normalized:
        format = PresentationFormat.TABLE
        style = ConversationStyle.REPORT
        depth = ExplanationDepth.DETAILED
        length = ResponseLength.LONG
    elif any(token in normalized for token in ("\uc790\uc138\ud788", "\uc790\uc138\ud558\uac8c", "\uc0c1\uc138\ud788", "\uc0c1\uc138\ud558\uac8c", "\uc790\uc138\ud55c \uacb0\uacfc", "\uc6d0\ubcf8", "\uc804\uccb4 \uacb0\uacfc")):
        format = PresentationFormat.BULLETS
        style = ConversationStyle.REPORT
        depth = ExplanationDepth.DETAILED
        length = ResponseLength.LONG
    elif any(token in normalized for token in ("\uc9e7\uac8c", "\uac04\ub2e8\ud788", "\uac04\ub2e8\ud558\uac8c", "\ud55c \uc904", "1\uc904")):
        format = PresentationFormat.PROSE
    if style is not original_style and not explicit_length:
        if style is ConversationStyle.REPORT:
            length = ResponseLength.LONG
        elif style in {ConversationStyle.TEACHING, ConversationStyle.PROFESSIONAL, ConversationStyle.EXPLANATORY, ConversationStyle.CONVERSATIONAL}:
            length = ResponseLength.MEDIUM
    return PresentationPreference(style=style, depth=depth, length=length, format=format, analogy_preference=analogy)


def render_presentation_from_payloads(payloads: tuple[dict[str, object], ...], *, intent: ConversationalMVPIntent, user_text: str, preference: PresentationPreference | None = None) -> str:
    pref = presentation_preference_for_text(user_text, preference)
    level = _presentation_level(pref)
    reasoning = build_reasoning_result(payloads, intent=intent, level=level, user_text=user_text)
    result = build_presentation_result(ConversationPresentationRequest(reasoning, user_text, pref), payloads)
    return render_presentation_result(result, payloads)


def build_presentation_result(request: ConversationPresentationRequest, payloads: tuple[dict[str, object], ...]) -> ConversationPresentationResult:
    pref = presentation_preference_for_text(request.user_text, request.preference)
    reasoning = request.reasoning
    warnings = tuple(_dedupe_warnings([limitation.message for limitation in reasoning.limitations] + [risk.message for risk in reasoning.risks]))[: _presentation_warning_limit(pref)]
    direct = _direct_answer_for(reasoning)
    explanation = _presentation_subject_context(payloads) + _presentation_explanation(reasoning, pref)
    analogy = _presentation_analogy(reasoning, pref)
    example = _presentation_example(payloads, pref, request.user_text)
    next_action = reasoning.next_actions[0].message if reasoning.next_actions else "\ucd94\uac00 \uac80\uc99d \ud6c4 \ub2e4\uc2dc \ud310\ub2e8\ud574\uc57c \ud569\ub2c8\ub2e4."
    refs = tuple(f"{symbol}:{reasoning.source}:{reasoning.quality_status}" for symbol in reasoning.symbols)
    return ConversationPresentationResult(
        style=pref.style,
        depth=pref.depth,
        length=pref.length,
        format=pref.format,
        direct_answer=direct,
        explanation=explanation,
        analogy=analogy,
        example=example,
        warnings=warnings,
        next_action=next_action,
        source_refs=refs,
        unsupported_claims_blocked=reasoning.unsupported_claims_blocked,
    )


def render_presentation_result(result: ConversationPresentationResult, payloads: tuple[dict[str, object], ...]) -> str:
    if result.format is PresentationFormat.TABLE:
        if len(payloads) > 1:
            return _sanitize_final(_comparison_markdown_table(payloads, result))
        return _sanitize_final(_single_markdown_table(payloads[0], result))
    if result.style is ConversationStyle.REPORT:
        if len(payloads) > 1:
            return _sanitize_final(render_symbol_comparison_detail(payloads))
        return _sanitize_final(render_single_symbol_summary(payloads[0], user_text="\uc790\uc138\ud788 \ubcf4\uc5ec\uc918"))
    if result.length is ResponseLength.ONE_LINE or result.style is ConversationStyle.CONCISE:
        sentences = [result.direct_answer, result.explanation]
        return _sanitize_final(" ".join(_dedupe_sentences(sentences)[:2]))
    if result.style is ConversationStyle.TEACHING:
        lines = [result.direct_answer, result.explanation]
        if result.analogy is not None:
            lines.append(result.analogy.text)
        if result.example is not None:
            lines.append(result.example.text)
        if result.warnings:
            lines.append(result.warnings[0])
        lines.append(result.next_action)
        return _sanitize_final("\n".join(_dedupe_sentences(lines)))
    if result.style is ConversationStyle.PROFESSIONAL:
        lines = [result.direct_answer, result.explanation, "\uc804\ubb38 \uc9c0\ud45c\ub85c \ubcf4\uba74 MDD, Sharpe, Profit Factor, Exposure, trade_count\ub97c \ud568\uaed8 \ubd10\uc57c \ud569\ub2c8\ub2e4."]
        lines.extend(result.warnings[:2])
        lines.append(result.next_action)
        return _sanitize_final("\n".join(_dedupe_sentences(lines)))
    lines = [result.direct_answer, result.explanation]
    if result.analogy is not None:
        lines.append(result.analogy.text)
    if result.example is not None:
        lines.append(result.example.text)
    lines.extend(result.warnings[:1 if result.length is ResponseLength.SHORT else 2])
    if result.length in {ResponseLength.MEDIUM, ResponseLength.LONG}:
        lines.append(result.next_action)
    return _sanitize_final("\n".join(_dedupe_sentences(lines)))


def _presentation_level(preference: PresentationPreference) -> ExplanationLevel:
    if preference.depth is ExplanationDepth.SIMPLE:
        return ExplanationLevel.SIMPLE
    if preference.depth is ExplanationDepth.PROFESSIONAL:
        return ExplanationLevel.PROFESSIONAL
    if preference.depth is ExplanationDepth.DETAILED:
        return ExplanationLevel.DETAILED
    return ExplanationLevel.STANDARD


def _direct_answer_for(reasoning: ConversationReasoningResult) -> str:
    if reasoning.intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST}:
        return "\ud604\uc7ac \uacb0\uacfc\ub9cc\uc73c\ub85c\ub294 \ub9e4\uc218\ub97c \ucd94\ucc9c\ud558\uae30 \uc5b4\ub835\uc2b5\ub2c8\ub2e4."
    if reasoning.intent is ConversationalMVPIntent.RISK_QUESTION:
        return "\uc704\ud5d8\uc740 \uad00\ucc30\ub410\uc9c0\ub9cc, \ud604\uc7ac \ud45c\ubcf8\ub9cc\uc73c\ub85c \uc2e4\uc81c \uc704\ud5d8 \uc218\uc900\uc744 \ud655\uc815\ud558\uae30\ub294 \uc5b4\ub835\uc2b5\ub2c8\ub2e4."
    if reasoning.intent is ConversationalMVPIntent.STRATEGY_QUESTION:
        return "\uc774 \uc804\ub7b5\uc740 \uc870\uac74\uacfc \uac80\uc99d \uacb0\uacfc\ub97c \ubd84\ub9ac\ud574\uc11c \ubd10\uc57c \ud569\ub2c8\ub2e4."
    return reasoning.conclusion


def _presentation_explanation(reasoning: ConversationReasoningResult, preference: PresentationPreference) -> str:
    points = reasoning.evidence_points
    first = points[0] if points else None
    second = points[1] if len(points) > 1 else None
    if preference.depth is ExplanationDepth.SIMPLE:
        if first is None:
            return "\uad6c\uc870\ud654\ub41c \uadfc\uac70\uac00 \ubd80\uc871\ud574\uc11c \ub354 \uc27d\uac8c \ud480\uc5b4 \ub9d0\ud560 \ub0b4\uc6a9\ub3c4 \uc81c\ud55c\uc801\uc785\ub2c8\ub2e4."
        return f"\ud575\uc2ec\uc740 {first.value}\ub77c\ub294 \uc810\uc785\ub2c8\ub2e4. {first.interpretation}"
    if first and second:
        return f"\ud575\uc2ec \uadfc\uac70\ub294 {first.label}\uc774 {first.value}\uc774\uace0, {second.label}\uc774 {second.value}\ub77c\ub294 \uc810\uc785\ub2c8\ub2e4. {first.interpretation}"
    if first:
        return f"\ud575\uc2ec \uadfc\uac70\ub294 {first.label}\uc774 {first.value}\ub77c\ub294 \uc810\uc785\ub2c8\ub2e4. {first.interpretation}"
    return "\uad6c\uc870\ud654\ub41c \uadfc\uac70\uac00 \ubd80\uc871\ud569\ub2c8\ub2e4."


def _presentation_subject_context(payloads: tuple[dict[str, object], ...]) -> str:
    if not payloads:
        return ""
    labels = tuple(f"{SYMBOL_NAMES.get(_symbol_from_payload(payload), _symbol_from_payload(payload))}({_symbol_from_payload(payload)})" for payload in payloads)
    metadata = _dict(_dict(payloads[0].get("dataset")).get("metadata"))
    source = _source_label(metadata)
    if len(labels) == 1:
        return f"\uc9c1\uc804 {labels[0]} \ubd84\uc11d \uae30\uc900\uc774\uba70 {source}\uc785\ub2c8\ub2e4. "
    return f"\uc9c1\uc804 \ube44\uad50 \ub300\uc0c1\uc740 {', '.join(labels)}\uc774\uace0 {source}\uc785\ub2c8\ub2e4. "


def _presentation_analogy(reasoning: ConversationReasoningResult, preference: PresentationPreference) -> Analogy | None:
    if preference.style is not ConversationStyle.TEACHING and not preference.analogy_preference:
        return None
    text = "\uac70\ub798 \ud45c\ubcf8\uc774 \uc801\ub2e4\ub294 \uac83\uc740 \uc2dc\ud5d8 \ubb38\uc81c\ub97c \ud55c\ub450 \uac1c\ub9cc \ud480\uace0 \uc2e4\ub825\uc744 \ud310\ub2e8\ud558\ub294 \uac83\uacfc \ube44\uc2b7\ud569\ub2c8\ub2e4. \uacb0\uacfc\uac00 \uc88b\uc544 \ubcf4\uc5ec\ub3c4 \uc2e4\ub825\uc774 \ubc18\ubcf5\ub418\ub294\uc9c0 \uc544\uc9c1 \uad6c\ubd84\ud558\uae30 \uc5b4\ub835\uc2b5\ub2c8\ub2e4."
    if any("\uac70\ub798 \ud45c\ubcf8" in point.label and point.value.startswith(("0", "1", "2", "3", "4")) for point in reasoning.evidence_points):
        return Analogy("trade_count", text)
    for point in reasoning.evidence_points:
        if "MDD" in point.label:
            text = "MDD\ub294 \uc790\uc0b0\uc774 \uace0\uc810\uc5d0\uc11c \uc5bc\ub9c8\ub098 \ub0b4\ub824\uac14\ub294\uc9c0\ub97c \ubcf4\ub294 \uc9c0\ud45c\uc785\ub2c8\ub2e4. \uc0b0 \uc815\uc0c1\uc5d0\uc11c \uc7a0\uc2dc \ub0b4\ub824\uc628 \ud3ed\uc744 \ubcf4\ub294 \uac83\ucc98\ub7fc, \uc218\uc775\ub960\ub9cc \ubcfc \ub54c \ub193\uce58\ub294 \ud754\ub4e4\ub9bc\uc744 \ubcf4\uc5ec\uc90d\ub2c8\ub2e4."
            break
    return Analogy("research_reliability", text)


def _presentation_example(payloads: tuple[dict[str, object], ...], preference: PresentationPreference, user_text: str) -> ExampleCalculation | None:
    if "\uc608\ub97c \ub4e4\uc5b4" not in user_text and preference.style is not ConversationStyle.TEACHING:
        return None
    if not payloads:
        return None
    payload = payloads[0]
    assumptions = _dict(payload.get("assumptions"))
    initial_capital = _provenanced_numeric(assumptions.get("initial_capital"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    mdd = _as_float(metrics.get("mdd"))
    if initial_capital is None or mdd is None:
        return None
    drawdown_amount = initial_capital * mdd
    remaining_equity = initial_capital * (1 - mdd)
    return ExampleCalculation(
        "mdd_example",
        "drawdown_amount = initial_capital * mdd; remaining_equity = initial_capital * (1 - mdd)",
        f"\uc608\ub97c \ub4e4\uc5b4 MDD {mdd:.2%}\ub97c \ucd08\uae30 \uc790\ubcf8 {initial_capital:,.0f}\uc6d0\uc5d0 \ub2e8\uc21c \uc801\uc6a9\ud558\uba74 \uace0\uc810 \ub300\ube44 \uc57d {drawdown_amount:,.0f}\uc6d0\uc758 \ub099\ud3ed, \uc57d {remaining_equity:,.0f}\uc6d0 \uc218\uc900\uc744 \uc608\uc2dc\ub85c \uc0dd\uac01\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4. \uc774\uac83\uc740 MDD\ub97c \ucd08\uae30 \uc790\ubcf8\uc5d0 \ub300\uc785\ud55c \uc124\uba85\uc6a9 \uc608\uc2dc\uc774\uba70, \uc2e4\uc81c \uc190\uc2e4\uc774 \ubc18\ub4dc\uc2dc \ucd08\uae30 \uc790\ubcf8\uc5d0\uc11c \uc9c1\uc811 \ubc1c\uc0dd\ud588\ub2e4\ub294 \ub73b\uc740 \uc544\ub2d9\ub2c8\ub2e4.",
    )


def _presentation_warning_limit(preference: PresentationPreference) -> int:
    if preference.length in {ResponseLength.ONE_LINE, ResponseLength.SHORT}:
        return 1
    if preference.length is ResponseLength.LONG or preference.style is ConversationStyle.REPORT:
        return 4
    return 2


def _dedupe_sentences(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = " ".join(line.strip().split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _comparison_markdown_table(payloads: tuple[dict[str, object], ...], result: ConversationPresentationResult) -> str:
    lines = [result.direct_answer, "", "| \uc885\ubaa9 | \ucd1d\uc218\uc775\ub960 | \ucd5c\ub300 \ub099\ud3ed | \uac70\ub798 \uc218 | \uc131\uacfc \uc2e0\ub8b0\ub3c4 | \ud574\uc11d \uac00\ub2a5 \uc5ec\ubd80 |", "|---|---:|---:|---:|---|---|"]
    for payload in payloads:
        symbol = _symbol_from_payload(payload)
        metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
        trade_count = _as_int(metrics.get("trade_count"))
        confidence = "\ub0ae\uc74c" if trade_count < 5 else "\ubcf4\ud1b5" if trade_count < 20 else "\ub192\uc74c"
        interpretable = "\uc81c\ud55c\uc801" if trade_count < 5 else "\uac00\ub2a5"
        lines.append(f"| {SYMBOL_NAMES.get(symbol, symbol)}({symbol}) | {_format_percent(metrics.get('total_return'))} | {_format_percent(metrics.get('mdd'))} | {trade_count}\ud68c | {confidence} | {interpretable} |")
    if result.warnings:
        lines.extend(["", "\uc8fc\uc758: " + result.warnings[0]])
    return "\n".join(lines)


def _single_markdown_table(payload: dict[str, object], result: ConversationPresentationResult) -> str:
    symbol = _symbol_from_payload(payload)
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    quality = _dict(payload.get("quality"))
    metadata = _dict(_dict(payload.get("dataset")).get("metadata"))
    lines = [
        result.direct_answer,
        "",
        "| \ud56d\ubaa9 | \uac12 |",
        "|---|---:|",
        f"| \uc885\ubaa9 | {SYMBOL_NAMES.get(symbol, symbol)}({symbol}) |",
        f"| \ub370\uc774\ud130 \ucd9c\ucc98 | {_source_label(metadata)} |",
        f"| \ub370\uc774\ud130 \ud488\uc9c8 | {_quality_label(quality.get('status'))} |",
        f"| \ucd1d\uc218\uc775\ub960 | {_format_percent(metrics.get('total_return'))} |",
        f"| MDD | {_format_percent(metrics.get('mdd'))} |",
        f"| \uac70\ub798 \uc218 | {_format_int(metrics.get('trade_count'))}\ud68c |",
        f"| Profit Factor | {_format_profit_factor(metrics.get('profit_factor'), metrics.get('trade_count'))} |",
    ]
    if result.warnings:
        lines.extend(["", "\uc8fc\uc758: " + result.warnings[0]])
    return "\n".join(lines)


def _presentation_reasoning_proxy(result: ConversationPresentationResult) -> ConversationReasoningResult:
    return ConversationReasoningResult(
        intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
        symbols=(),
        conclusion=result.direct_answer,
        evidence_points=(EvidencePoint("\uc124\uba85", "\uc694\uc57d", result.explanation),),
        limitations=tuple(Limitation(item) for item in result.warnings),
        risks=(),
        next_actions=(NextAction(result.next_action),),
        explanation_level=ExplanationLevel.DETAILED,
        source="presentation",
        fixture_backed=False,
        quality_status="presentation",
        confidence="\ubcf4\ub958",
        unsupported_claims_blocked=result.unsupported_claims_blocked,
        decision_boundary=DecisionBoundary(True, "\ud45c\ud604 \ubc29\uc2dd\ub9cc \ubcc0\uacbd\ud588\uc2b5\ub2c8\ub2e4."),
    )

def render_rerun_boundary(context: ConversationalMVPContext, intent: ConversationalMVPIntent) -> str:
    symbols = ", ".join(context.last_symbols) if context.last_symbols else "직전 종목"
    return _sanitize_final(
        "\n".join(
            [
                "[결론]",
                f"- {symbols}에 대한 재검증 요청으로 이해했습니다. 다만 이번 답변에서는 기존 결과를 임의로 다시 계산하거나 전략 조건을 바꾸지 않겠습니다.",
                "",
                "[필요한 확인]",
                "- 재검증할 기간을 명확히 지정해 주세요. 예: 3년, 5년, 2021-07-25~2026-07-24.",
                "- 변경할 전략 조건이 있다면 사용자 제공 조건으로 분리해서 알려 주세요.",
                "",
                "[안전 경계]",
                "- 사용자 승인 없는 전략 변경, Champion 승격, 주문 실행은 하지 않습니다.",
            ]
        )
    )


def render_single_symbol_explanation(payload: dict[str, object], context: ConversationalMVPContext | None = None) -> str:
    symbol = _symbol_from_payload(payload)
    name = SYMBOL_NAMES.get(symbol, symbol)
    metadata = _dict(_dict(payload.get("dataset")).get("metadata"))
    quality = _dict(payload.get("quality"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    lines = [
        f"영하님, 직전 {name}({symbol}) 분석 판단 근거는 저장된 구조화 결과입니다.",
        f"- 데이터: {_source_label(metadata)}",
        f"- 데이터 품질: {_quality_label(quality.get('status'))}. 이것은 데이터 검사를 통과했다는 뜻이지, 전략 성과가 검증됐다는 뜻은 아닙니다.",
        f"- 거래 수: {_format_int(metrics.get('trade_count'))}회",
        f"- 총 수익률: {_format_percent(metrics.get('total_return'))}",
        f"- MDD: {_format_percent(metrics.get('mdd'))}",
    ]
    warnings = _reliability_warnings(payload)
    if warnings:
        lines.extend(["", "[신뢰도 주의]", *[f"- {warning}" for warning in warnings]])
    lines.extend(["", "따라서 성과 숫자만 보지 않고 표본 수, 손실 폭, 데이터 품질을 함께 본 것입니다."])
    return _sanitize_final("\n".join(lines))


def render_symbol_comparison_explanation(payloads: tuple[dict[str, object], ...], context: ConversationalMVPContext | None = None) -> str:
    lines = ["영하님, 직전 비교 판단은 각 종목을 같은 조건으로 실행한 구조화 결과만 기준으로 설명드립니다.", ""]
    for payload in payloads:
        lines.extend(_comparison_explanation_lines(payload))
        warnings = _reliability_warnings(payload)
        if warnings:
            lines.extend([f"- 주의: {warning}" for warning in warnings])
        lines.append("")
    lines.append("이 판단에는 직전 비교 결과가 아닌 다른 상태 조회나 과거 테스트 결과를 섞지 않았습니다.")
    return _sanitize_final("\n".join(lines))


def render_single_symbol_simple(payload: dict[str, object]) -> str:
    symbol = _symbol_from_payload(payload)
    name = SYMBOL_NAMES.get(symbol, symbol)
    quality = _dict(payload.get("quality"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    lines = [
        f"영하님, 쉽게 말하면 직전 {name}({symbol}) 결과는 이렇게 보면 됩니다.",
        f"- 실제로 확인된 거래는 {trade_count}회입니다.",
        f"- 데이터 품질은 {_quality_label(quality.get('status'))}입니다.",
    ]
    if trade_count == 0:
        lines.append("- 거래가 없어 전략 성과를 직접 평가할 수 없습니다.")
    else:
        lines.append("- 표본이 적으면 수익률이나 승률이 좋아 보여도 믿을 수 있는 전략이라고 말할 수 없습니다.")
    warnings = _reliability_warnings(payload)
    if warnings:
        lines.append(f"- 핵심 주의점: {warnings[0]}")
    return _sanitize_final("\n".join(lines))


def render_symbol_comparison_simple(payloads: tuple[dict[str, object], ...]) -> str:
    lines = ["영하님, 쉽게 말하면 직전 비교는 같은 조건으로 종목별 결과를 나란히 본 것입니다."]
    for payload in payloads:
        symbol = _symbol_from_payload(payload)
        name = SYMBOL_NAMES.get(symbol, symbol)
        quality = _dict(payload.get("quality"))
        metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
        trade_count = _as_int(metrics.get("trade_count"))
        if trade_count == 0:
            metric_text = "거래 0회, 성과 평가 불가"
        else:
            metric_text = f"거래 {trade_count}회, 관측된 총 수익률 {_format_percent(metrics.get('total_return'))}"
        lines.append(f"- {name}({symbol}): {metric_text}, {_quality_label(quality.get('status'))}")
    lines.append("- 표본이 부족하므로 어느 종목이 더 좋다고 확정하지 않습니다.")
    return _sanitize_final("\n".join(lines))


def render_symbol_comparison_detail(payloads: tuple[dict[str, object], ...]) -> str:
    lines = ["영하님, 직전 비교의 상세 구조화 결과입니다.", ""]
    for payload in payloads:
        symbol = _symbol_from_payload(payload)
        name = SYMBOL_NAMES.get(symbol, symbol)
        metadata = _dict(_dict(payload.get("dataset")).get("metadata"))
        quality = _dict(payload.get("quality"))
        strategy = _dict(payload.get("strategy"))
        metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
        lines.extend(
            [
                f"[{name}({symbol})]",
                f"- 기간: {metadata.get('start_date', 'unknown')} ~ {metadata.get('end_date', 'unknown')}",
                f"- 데이터: {_source_label(metadata)}",
                f"- {_quality_label(quality.get('status'))}",
                f"- 총 수익률: {_format_percent(metrics.get('total_return'))}",
                f"- MDD: {_format_percent(metrics.get('mdd'))}",
                f"- 거래 수: {_format_int(metrics.get('trade_count'))}회",
                f"- Profit Factor: {_format_profit_factor(metrics.get('profit_factor'), metrics.get('trade_count'))}",
                *_detail_lines(payload, strategy, metrics),
            ]
        )
        warnings = _reliability_warnings(payload)
        if warnings:
            lines.extend(["- 종목별 주의:", *[f"  - {warning}" for warning in warnings]])
        lines.append("")
    return _sanitize_final("\n".join(lines))


def _comparison_explanation_lines(payload: dict[str, object]) -> list[str]:
    symbol = _symbol_from_payload(payload)
    name = SYMBOL_NAMES.get(symbol, symbol)
    metadata = _dict(_dict(payload.get("dataset")).get("metadata"))
    quality = _dict(payload.get("quality"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    lines = [
        f"[{name}({symbol})]",
        f"- 데이터: {_source_label(metadata)}",
        f"- {_quality_label(quality.get('status'))}: 데이터 품질 상태이며 전략 유효성 판정이 아닙니다.",
        f"- 거래 수: {trade_count}회",
    ]
    if trade_count == 0:
        lines.append("- 진입 신호가 없어 성과 수치와 위험 수치를 직접 비교할 수 없습니다.")
    else:
        lines.extend(
            [
                f"- 관측된 총 수익률: {_format_percent(metrics.get('total_return'))}",
                f"- MDD: {_format_percent(metrics.get('mdd'))}",
            ]
        )
    return lines


def _is_simple_greeting(normalized: str) -> bool:
    compact = re.sub(r"\s+", "", normalized)
    return compact in {"안녕", "안녕하세요", "가온", "가온아", "hello", "hi", "gaon"}


def _classify_followup_typo(normalized: str) -> ConversationalMVPIntent | None:
    compact = _compact_followup_text(normalized)
    if _matches_any(compact, _DETAIL_ALIASES):
        return ConversationalMVPIntent.SHOW_DETAILS
    if _matches_any(compact, _SIMPLIFY_ALIASES):
        return ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT
    if _matches_any(compact, _EXPLAIN_ALIASES) or ("왜" in compact and any(token in compact for token in ("판단", "판간", "그렇", "그런", "그절", "이유"))):
        return ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT
    return None


def _compact_followup_text(value: str) -> str:
    return re.sub(r"[\s\?\!\.\,\~\ㅠ\ㅜ]+", "", value.casefold())


def _matches_any(compact: str, aliases: tuple[str, ...]) -> bool:
    for alias in aliases:
        candidate = _compact_followup_text(alias)
        if candidate and candidate in compact:
            return True
        if candidate and _levenshtein_limited(compact, candidate, 2) <= 2:
            return True
    return False


def _levenshtein_limited(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, 1):
        current = [i]
        row_min = i
        for j, char_right in enumerate(right, 1):
            cost = 0 if char_left == char_right else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _symbol_from_payload(payload: dict[str, object]) -> str:
    dataset = _dict(payload.get("dataset"))
    symbols = dataset.get("symbols")
    if isinstance(symbols, list) and symbols and isinstance(symbols[0], dict):
        return str(symbols[0].get("symbol", "005930"))
    return str(payload.get("symbol", "005930"))


def _source_label(metadata: dict[str, object]) -> str:
    fixture = metadata.get("fixture_backed")
    source = metadata.get("source", "unknown")
    if fixture is True:
        return "데이터 출처: 테스트용 fixture"
    if str(source) == "real:yahoo-chart":
        return "데이터 출처: Yahoo Chart 공개 데이터"
    return "데이터 출처: 확인된 연구 데이터"


def _quality_label(status: object) -> str:
    value = str(status or "unknown")
    if value == "pass":
        return "데이터 무결성 검토 통과"
    if value in {"pass_with_warnings", "warning"}:
        return "데이터 무결성 검토 경고 있음"
    if value == "fail":
        return "데이터 무결성 검토 실패"
    return "데이터 무결성 상태 확인 필요"


def _confidence_label(confidence: str) -> str:
    if confidence == "낮음":
        return "성과 신뢰도: 낮음"
    if confidence == "보통":
        return "성과 신뢰도: 보통"
    if confidence == "높음":
        return "성과 신뢰도: 높음"
    return "성과 신뢰도: 판단 보류"


def _one_line_conclusion(metrics: dict[str, object]) -> str:
    trade_count = _as_int(metrics.get("trade_count"))
    total_return = _as_float(metrics.get("total_return"))
    mdd = _as_float(metrics.get("mdd"))
    if trade_count == 0:
        return "거래가 없어 전략 성과를 직접 평가할 수 없습니다."
    if trade_count < 5:
        return "거래 표본이 매우 적어 성과 판단보다 추가 검증이 우선입니다."
    if total_return is not None and total_return > 0 and (mdd is None or mdd < 0.2):
        return "성과는 긍정적이지만 표본과 리스크를 함께 확인해야 합니다."
    return "현재 구조화된 결과만으로는 강한 우위 판단을 보류하는 것이 맞습니다."


def _reliability_warnings(payload: dict[str, object]) -> list[str]:
    dataset = _dict(payload.get("dataset"))
    metadata = _dict(dataset.get("metadata"))
    quality = _dict(payload.get("quality"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    warnings: list[str] = []
    if trade_count == 0:
        warnings.append("거래가 없어 수익률, MDD, 승률, Profit Factor를 전략 성과로 해석할 수 없습니다.")
    elif trade_count == 1:
        warnings.append("주의: 거래 표본이 1건뿐이므로 수익률, 승률, CAGR과 Profit Factor를 신뢰하기 어렵습니다.")
    elif trade_count < 5:
        warnings.append("거래 표본이 5건 미만이라 통계적 신뢰도가 매우 낮습니다.")
    elif trade_count < 20:
        warnings.append("거래 표본이 20건 미만이라 통계적 신뢰도가 낮습니다.")
    profit_factor = metrics.get("profit_factor")
    if trade_count > 0 and _is_inf(profit_factor):
        warnings.append("Profit Factor는 손실 거래가 없어서 계산상 무한대로 보일 수 있으며 강한 성과 근거로 해석하지 않습니다.")
    if trade_count > 0 and _as_float(metrics.get("win_rate")) == 1.0 and trade_count < 20:
        warnings.append("승률 100%처럼 보이지만 거래 수가 적어 신뢰하기 어렵습니다.")
    if metadata.get("fixture_backed") is True:
        warnings.append("fixture 데이터 기반 결과이므로 실제 시장 결과처럼 해석하지 않습니다.")
    if quality.get("status") not in {"pass", None}:
        warnings.append(f"데이터 품질 상태가 {quality.get('status')}입니다. 경고 내용을 함께 확인해야 합니다.")
    return _dedupe_warnings(warnings)


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        normalized = _normalize_warning(warning)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_warning(warning: str) -> str:
    value = warning.strip()
    changed = True
    while changed:
        changed = False
        for prefix in ("주의:", "경고:", "위험:"):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
                changed = True
    return value


def _risk_lines(payload: dict[str, object]) -> list[str]:
    risks = _reliability_warnings(payload)
    if not risks:
        risks.append("백테스트 결과는 주문이나 Champion 승격 근거가 아니며 별도 승인과 운영 검증이 필요합니다.")
    return risks[:5]


def _detail_lines(payload: dict[str, object], strategy: dict[str, object], metrics: dict[str, object]) -> list[str]:
    assumptions = _dict(payload.get("assumptions"))
    initial_capital = _provenanced_numeric(assumptions.get("initial_capital"))
    return [
        f"- CAGR: {_format_metric('cagr', metrics.get('cagr'))}",
        f"- Sharpe: {_format_metric('sharpe', metrics.get('sharpe'))}",
        f"- 승률: {_format_metric('win_rate', metrics.get('win_rate'))}",
        f"- 평균 거래 손익: {_format_metric('average_trade', metrics.get('average_trade'))}",
        f"- 평균 이익 거래: {_format_metric('average_win', metrics.get('average_win'))}",
        f"- 평균 손실 거래: {_format_metric('average_loss', metrics.get('average_loss'))}",
        f"- 평균 거래 기대손익: {_format_expectancy(metrics.get('expectancy'), initial_capital)}",
        f"- 노출 비율: {_format_metric('exposure', metrics.get('exposure'))}",
        f"- 최종 자산: {_format_metric('ending_equity', metrics.get('ending_equity'))}",
    ]


def _reasoning_evidence_points(payload: dict[str, object]) -> tuple[EvidencePoint, ...]:
    symbol = _symbol_from_payload(payload)
    name = SYMBOL_NAMES.get(symbol, symbol)
    metadata = _dict(_dict(payload.get("dataset")).get("metadata"))
    quality = _dict(payload.get("quality"))
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    points = [
        EvidencePoint(f"{name} 거래 표본", f"{trade_count}회", _trade_count_interpretation(trade_count)),
        EvidencePoint(f"{name} 총 수익률", _format_percent(metrics.get("total_return")), "관측된 백테스트 결과이며 미래 성과 보장이 아닙니다."),
        EvidencePoint(f"{name} 최대 낙폭(MDD)", _format_percent(metrics.get("mdd")), _mdd_interpretation(metrics.get("mdd"), trade_count)),
        EvidencePoint(f"{name} 데이터", _source_label(metadata), f"{_quality_label(quality.get('status'))}. 데이터 검사를 통과해도 전략 유효성이 검증된 것은 아닙니다."),
    ]
    if trade_count > 0:
        points.extend(
            [
                EvidencePoint(f"{name} 승률", _format_percent(metrics.get("win_rate")), "표본 수와 함께 해석해야 합니다."),
                EvidencePoint(f"{name} Profit Factor", _format_profit_factor(metrics.get("profit_factor"), trade_count), "손실 거래가 적거나 없으면 과대 해석하면 안 됩니다."),
            ]
        )
    if any(key in metrics for key in ("sharpe", "exposure")):
        points.extend(
            [
                EvidencePoint(f"{name} Sharpe", _format_metric("sharpe", metrics.get("sharpe")), "거래 표본이 적으면 위험 조정 성과 근거가 약합니다."),
                EvidencePoint(f"{name} Exposure", _format_metric("exposure", metrics.get("exposure")), "시장에 투자되어 있던 기간의 비율입니다."),
            ]
        )
    return tuple(points)


def _reasoning_limitations(payload: dict[str, object], intent: ConversationalMVPIntent) -> tuple[str, ...]:
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    quality = _dict(payload.get("quality"))
    trade_count = _as_int(metrics.get("trade_count"))
    items: list[str] = []
    if trade_count == 0:
        items.append("해당 기간에는 전략 진입 신호가 없어 수익률과 위험 지표를 충분한 근거로 볼 수 없습니다.")
    elif trade_count < 5:
        items.append("거래 표본이 5건 미만이므로 승률, Profit Factor, CAGR은 일반화하기 어렵습니다.")
    elif trade_count < 20:
        items.append("거래 표본이 20건 미만이므로 통계적 신뢰도는 제한적입니다.")
    if quality.get("status") == "pass":
        items.append("데이터 무결성 검토 통과는 입력 데이터 품질 의미이며, 전략 성과 검증과는 별개입니다.")
    elif quality.get("status") not in {None, "pass"}:
        items.append("데이터 품질 경고가 있으므로 경고 날짜와 원인을 함께 확인해야 합니다.")
    if intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST}:
        items.append("현재 근거만으로 매수, 매도, 보유 같은 투자 결정을 권하지 않습니다.")
    return tuple(items)


def _reasoning_risks(payload: dict[str, object]) -> tuple[str, ...]:
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    risks = list(_reliability_warnings(payload))
    if trade_count == 0:
        risks.append("0% 수익률이나 0% MDD를 위험이 낮다는 뜻으로 해석할 수 없습니다.")
    mdd = _as_float(metrics.get("mdd"))
    if mdd is not None and mdd > 0:
        risks.append(f"백테스트 중 고점 대비 최대 {_format_percent(mdd)}의 자산 감소가 관측됐습니다.")
    return tuple(_dedupe_warnings(risks))


def _reasoning_next_actions(payload: dict[str, object], intent: ConversationalMVPIntent) -> tuple[str, ...]:
    metrics = _dict(_dict(payload.get("backtest")).get("metrics"))
    trade_count = _as_int(metrics.get("trade_count"))
    actions = ["더 긴 기간과 여러 시장 구간에서 재검증해 거래 표본을 늘려야 합니다."]
    if trade_count == 0:
        actions.append("진입 조건이 너무 엄격한지 사용자 제공 전략 조건을 분리해 다시 점검해야 합니다.")
    if intent is ConversationalMVPIntent.RISK_QUESTION:
        actions.append("MDD, 손실 거래, 노출 기간을 함께 보고 위험을 다시 평가해야 합니다.")
    if intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST}:
        actions.append("매수 판단 전에 기간 확장, 다종목 검증, 개선 후보의 TESTED 결과를 확인해야 합니다.")
    return tuple(actions)


def _reasoning_confidence(payloads: tuple[dict[str, object], ...]) -> str:
    trade_counts = [_as_int(_dict(_dict(payload.get("backtest")).get("metrics")).get("trade_count")) for payload in payloads]
    if not trade_counts or min(trade_counts) < 5:
        return "낮음"
    if min(trade_counts) < 20:
        return "보통"
    return "높음"


def _blocked_claims(intent: ConversationalMVPIntent) -> tuple[str, ...]:
    claims = [
        "매수 또는 매도 추천",
        "전략이 검증됐다는 확정 표현",
        "표본 부족 상태에서 우월성 확정",
        "주문 실행 또는 자동 승인",
    ]
    if intent is ConversationalMVPIntent.RISK_QUESTION:
        claims.append("거래 0건 또는 표본 부족을 위험 없음으로 해석")
    return tuple(claims)


def _decision_boundary(intent: ConversationalMVPIntent, payloads: tuple[dict[str, object], ...]) -> DecisionBoundary:
    if intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST}:
        return DecisionBoundary(False, "가온은 현재 근거만으로 투자 주문이나 매수/매도 추천을 하지 않습니다.")
    if not payloads:
        return DecisionBoundary(False, "직전 연구 근거가 없어 판단하지 않습니다.")
    return DecisionBoundary(True, "구조화된 백테스트 근거 안에서만 설명합니다.")


def _reasoning_conclusion(intent: ConversationalMVPIntent, payloads: tuple[dict[str, object], ...]) -> str:
    if not payloads:
        return "직전에 설명할 연구 결과가 없습니다."
    if intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST}:
        return "현재 구조화된 근거만으로 매수나 추천을 확정하기는 어렵습니다."
    if intent is ConversationalMVPIntent.RISK_QUESTION:
        return "위험은 주로 거래 표본 부족, MDD, 데이터 품질 의미의 오해에서 발생합니다."
    if intent is ConversationalMVPIntent.STRATEGY_QUESTION:
        return "전략 조건은 사용자 제공 조건과 백테스트 관측 결과를 분리해서 봐야 합니다."
    if len(payloads) > 1:
        return "직전 비교 결과는 같은 조건의 관측값 비교이며, 우열 확정 근거는 아닙니다."
    metrics = _dict(_dict(payloads[0].get("backtest")).get("metrics"))
    return _one_line_conclusion(metrics)


def _trade_count_interpretation(trade_count: int) -> str:
    if trade_count == 0:
        return "진입 신호가 없어 성과와 위험을 일반화할 수 없습니다."
    if trade_count < 5:
        return "표본이 매우 적어 반복적으로 작동했다고 보기 어렵습니다."
    if trade_count < 20:
        return "관측값은 있으나 통계적 신뢰도는 제한적입니다."
    return "표본 수는 기본 해석이 가능한 수준입니다."


def _mdd_interpretation(value: object, trade_count: int) -> str:
    if trade_count == 0:
        return "거래가 없으면 0% MDD도 위험 없음이라는 뜻이 아닙니다."
    mdd = _as_float(value)
    if mdd is None:
        return "MDD가 계산되지 않았습니다."
    return f"백테스트 중 고점 대비 최대 {_format_percent(mdd)}의 자산 감소가 관측됐습니다."


def _reasoning_limit(level: ExplanationLevel, *, default: int) -> int:
    if level is ExplanationLevel.SIMPLE:
        return 1
    if level is ExplanationLevel.STANDARD:
        return default
    if level is ExplanationLevel.PROFESSIONAL:
        return max(default, 6)
    return 20


def _comparison_conclusion(rows: list[tuple[str, str, dict[str, object], dict[str, object], list[str]]]) -> str:
    if any(_as_int(row[2].get("trade_count")) == 0 for row in rows):
        return "거래가 없는 종목이 있어 직접 비교가 불가능합니다. 어느 종목이 더 좋다고 확정하지 않습니다."
    if any(warnings for *_, warnings in rows):
        return "표본 또는 데이터 품질 경고가 있어 확정적 우열은 보류합니다."
    ranked = sorted(rows, key=lambda row: (_as_float(row[2].get("total_return")) or -999.0, -(_as_float(row[2].get("mdd")) or 999.0)), reverse=True)
    return f"구조화된 지표만 보면 {ranked[0][1]}({ranked[0][0]})가 상대적으로 앞서지만 주문이나 승격 판단은 아닙니다."


def _format_metric(metric: str, value: object) -> str:
    if metric in RATIO_METRICS:
        return _format_percent(value)
    if metric in CURRENCY_METRICS:
        return _format_currency(value)
    if metric in COUNT_METRICS:
        return _format_count(value)
    if metric in DIMENSIONLESS_METRICS:
        if metric == "profit_factor":
            return _format_profit_factor(value, 1)
        return _format_dimensionless(value)
    return _format_optional_float(value)


def _format_percent(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.2%}"


def _format_currency(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:,.2f}"


def _format_count(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{int(numeric)}"


def _format_optional_float(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.4f}"


def _format_dimensionless(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.4f}"


def _format_int(value: object) -> str:
    return str(_as_int(value))


def _format_number(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.4f}"


def _format_profit_factor(value: object, trade_count: object) -> str:
    if _as_int(trade_count) == 0:
        return "거래 없음으로 계산 불가"
    if _is_inf(value):
        return "손실 거래 없음으로 해석 제한"
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.2f}"


def _format_expectancy(value: object, initial_capital: float | None) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    text = _format_currency(numeric)
    if initial_capital and initial_capital > 0:
        text = f"{text} (초기 자본 대비 {numeric / initial_capital:.2%})"
    return text


def _provenanced_numeric(value: object) -> float | None:
    if isinstance(value, dict):
        return _as_float(value.get("value"))
    return _as_float(value)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        if math.isfinite(float(value)):
            return float(value)
        return None
    try:
        parsed = float(str(value))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _as_int(value: object) -> int:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None else 0


def _is_inf(value: object) -> bool:
    return value == "inf" or (isinstance(value, float) and math.isinf(value))


def _sanitize_final(text: str) -> str:
    forbidden = ("validation_id", "strategy_fingerprint", "run_id", "provenance", "fixture_backed", "schema_version", "None", " inf", "RealBacktestResult", "CandidateComparison")
    sanitized = text.replace("<output>", "").replace("</output>", "").replace("<response>", "").replace("</response>", "")
    for token in forbidden:
        sanitized = sanitized.replace(token, "")
    return sanitized
