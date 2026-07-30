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
    SHOW_DETAILS = "show_details"
    STATUS_QUERY = "status_query"
    UNKNOWN = "unknown"


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
    last_research_result_ids: tuple[str, ...]
    last_rendered_result: str
    last_payloads: tuple[dict[str, object], ...]
    detail_level: str
    created_at: str


SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "005930": ("005930", "삼성전자", "삼성 전자", "samsung electronics", "samsung"),
    "000660": ("000660", "SK하이닉스", "SK 하이닉스", "에스케이하이닉스", "하이닉스", "sk hynix", "hynix"),
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

COMPARISON_TOKENS = ("비교", "차이", "어느 쪽", "뭐가 더", "와", "랑", "하고", " vs ", "versus", "compare")
ANALYSIS_TOKENS = ("분석", "백테스트", "검증", "연구", "살펴", "봐줘", "알려줘", "analysis", "backtest")
MULTI_SYMBOL_TOKENS = ("여러 종목", "다종목", "전체 종목", "유니버스", "상위", "universe", "multi-symbol", "multisymbol")
DETAIL_TOKENS = ("자세히", "원본", "전체 결과", "상세", "detail", "raw")
SIMPLIFY_TOKENS = ("쉽게", "간단히", "요약", "초등", "쉽게 설명", "simple")
EXPLAIN_TOKENS = ("왜", "이유", "판단", "근거", "그렇게", "explain")
STATUS_TOKENS = ("상태", "status", "정상", "런타임")


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
    if _is_simple_greeting(normalized):
        return ConversationalRoute(ConversationalMVPIntent.GREETING, ())
    if any(token in normalized for token in ("도움말", "뭘 할 수", "무엇을 할 수", "help", "/help", "/start")):
        return ConversationalRoute(ConversationalMVPIntent.HELP, symbols)
    if any(token in normalized for token in DETAIL_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.SHOW_DETAILS, symbols)
    if any(token in normalized for token in SIMPLIFY_TOKENS):
        return ConversationalRoute(ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT, symbols)
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
            "영하님, 지금은 다음 대화를 안전하게 도와드릴 수 있습니다.",
            "- 삼성전자 분석해줘",
            "- 삼성전자와 SK하이닉스 비교해줘",
            "- 왜 그렇게 판단했어?",
            "- 쉽게 설명해줘",
            "- 자세히 보여줘",
            "실거래 주문, 자동 승인, Champion 자동 승격은 수행하지 않습니다.",
        ]
    )


def render_unknown(symbols: tuple[SymbolEntity, ...] = ()) -> str:
    if symbols:
        names = ", ".join(f"{item.name}({item.symbol})" for item in symbols)
        return f"영하님, {names}는 인식했지만 요청 의도를 정확히 판단하지 못했습니다. '분석해줘' 또는 '비교해줘'처럼 말씀해 주세요."
    return "죄송하지만 요청을 정확히 이해하지 못했습니다, 영하님. 예: '삼성전자 분석해줘', '삼성전자와 SK하이닉스 비교해줘'처럼 말씀해 주세요."


def render_status() -> str:
    return "가온 대화 런타임은 응답 가능합니다, 영하님. 다만 실제 연구는 데이터 품질 검증과 safe tool 경계를 통과한 결과만 말씀드리겠습니다."


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
        f"영하님, {name}({symbol}) 실제 연구 결과입니다.",
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
            f"- quality_status={quality.get('status', 'unknown')}",
            f"- source={metadata.get('source', 'unknown')}",
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
            f"confidence={confidence}, quality_status={quality.get('status', 'unknown')}"
        )
    lines.extend(["", "[판단]", _comparison_conclusion(rows), "", "[주의]"])
    lines.extend(f"- {warning}" for _, _, _, _, warnings in rows for warning in warnings)
    if not any(warnings for _, _, _, _, warnings in rows):
        lines.append("- 모든 결론은 구조화된 백테스트 결과 안에서만 해석했습니다.")
    return _sanitize_final("\n".join(lines))


def render_follow_up(context: ConversationalMVPContext, intent: ConversationalMVPIntent) -> str:
    if intent is ConversationalMVPIntent.SHOW_DETAILS:
        if context.last_payloads:
            return render_single_symbol_summary(context.last_payloads[0], user_text="", detail_level="detail")
        return context.last_rendered_result
    if intent is ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT:
        symbols = ", ".join(context.last_symbols) or "직전 결과"
        return f"영하님, 쉽게 말하면 {symbols} 연구는 '성과 숫자보다 표본 수와 데이터 품질을 먼저 봐야 하는 결과'입니다. 거래 수가 적으면 수익률이나 승률이 좋아 보여도 신뢰하기 어렵습니다."
    return "영하님, 그렇게 판단한 이유는 구조화된 백테스트 지표, 거래 수, MDD, 데이터 품질 상태를 함께 봤기 때문입니다. 가온은 저장된 결과에 없는 성과 숫자는 만들지 않습니다."


def _is_simple_greeting(normalized: str) -> bool:
    compact = re.sub(r"\s+", "", normalized)
    return compact in {"안녕", "안녕하세요", "가온", "가온아", "hello", "hi", "gaon"}


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
        return f"{source} (fixture, 실제 데이터 아님)"
    return str(source)


def _one_line_conclusion(metrics: dict[str, object]) -> str:
    trade_count = _as_int(metrics.get("trade_count"))
    total_return = _as_float(metrics.get("total_return"))
    mdd = _as_float(metrics.get("mdd"))
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
    if trade_count == 1:
        warnings.append("주의: 거래 표본이 1건뿐이므로 수익률, 승률, CAGR과 Profit Factor를 신뢰하기 어렵습니다.")
    elif trade_count < 5:
        warnings.append("거래 표본이 5건 미만이라 통계적 신뢰도가 매우 낮습니다.")
    elif trade_count < 20:
        warnings.append("거래 표본이 20건 미만이라 통계적 신뢰도가 낮습니다.")
    profit_factor = metrics.get("profit_factor")
    if _is_inf(profit_factor):
        warnings.append("Profit Factor는 손실 거래가 없어서 계산상 무한대로 보일 수 있으며, 강한 성과 근거로 해석하지 않습니다.")
    if _as_float(metrics.get("win_rate")) == 1.0 and trade_count < 20:
        warnings.append("승률 100%처럼 보이지만 거래 수가 적어 신뢰하기 어렵습니다.")
    if metadata.get("fixture_backed") is True:
        warnings.append("fixture 데이터 기반 결과이므로 실제 시장 결과처럼 해석하지 않습니다.")
    if quality.get("status") not in {"pass", None}:
        warnings.append(f"데이터 품질 상태가 {quality.get('status')}입니다. 경고 내용을 함께 확인해야 합니다.")
    return warnings


def _risk_lines(payload: dict[str, object]) -> list[str]:
    risks = _reliability_warnings(payload)
    if not risks:
        risks.append("백테스트 결과는 주문이나 Champion 승격 근거가 아니며 별도 승인과 운영 검증이 필요합니다.")
    return risks[:5]


def _detail_lines(payload: dict[str, object], strategy: dict[str, object], metrics: dict[str, object]) -> list[str]:
    lines = [
        f"- strategy_fingerprint={strategy.get('fingerprint', 'unknown')}",
        f"- CAGR={_format_percent(metrics.get('cagr'))}",
        f"- Sharpe={_format_number(metrics.get('sharpe'))}",
        f"- Expectancy={_format_percent(metrics.get('expectancy'))}",
        f"- Exposure={_format_percent(metrics.get('exposure'))}",
    ]
    return lines


def _comparison_conclusion(rows: list[tuple[str, str, dict[str, object], dict[str, object], list[str]]]) -> str:
    if any(warnings for *_, warnings in rows):
        return "표본 또는 데이터 품질 경고가 있어 단정적 우열은 보류합니다."
    ranked = sorted(rows, key=lambda row: (_as_float(row[2].get("total_return")) or -999.0, -(_as_float(row[2].get("mdd")) or 999.0)), reverse=True)
    return f"구조화된 지표만 보면 {ranked[0][1]}({ranked[0][0]})가 상대적으로 앞서지만, 주문이나 승격 판단은 아닙니다."


def _format_percent(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.2%}"


def _format_int(value: object) -> str:
    return str(_as_int(value))


def _format_number(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "계산 불가"
    return f"{numeric:.4f}"


def _format_profit_factor(value: object, trade_count: object) -> str:
    if _is_inf(value):
        return "손실 거래 없음으로 해석 제한"
    numeric = _as_float(value)
    if numeric is None or _as_int(trade_count) == 0:
        return "계산 불가"
    return f"{numeric:.2f}"


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
    forbidden = ("validation_id", "provenance", "fixture_backed", "None", " inf", "RealBacktestResult", "CandidateComparison")
    sanitized = text.replace("<output>", "").replace("</output>", "").replace("<response>", "").replace("</response>", "")
    for token in forbidden:
        sanitized = sanitized.replace(token, "")
    return sanitized
