"""Deterministic contracts for conversational research re-execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any


@dataclass(frozen=True)
class ConversationalResearchExecutionRequest:
    intent: str
    symbols: tuple[str, ...]
    requested_period: str | None
    start_date: str | None
    end_date: str | None
    reuse_previous_strategy: bool
    reuse_previous_assumptions: bool
    comparison_requested: bool
    source_context_id: str | None
    user_provided_fields: dict[str, object]
    inferred_fields: dict[str, object]
    requires_confirmation: bool


@dataclass(frozen=True)
class ConversationalResearchExecutionResult:
    execution_status: str
    symbols: tuple[str, ...]
    resolved_start_date: str | None
    resolved_end_date: str | None
    research_results: tuple[dict[str, object], ...]
    previous_results: tuple[dict[str, object], ...]
    comparison: dict[str, object]
    data_quality: tuple[dict[str, object], ...]
    limitations: tuple[str, ...]
    execution_evidence: tuple[str, ...]


_SYMBOL_LABELS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "035420": "NAVER",
    "051910": "LG화학",
}


def build_conversational_research_execution_request(text: str, context: Any, *, received_at: str) -> ConversationalResearchExecutionRequest:
    normalized = text.casefold()
    explicit_symbols = _extract_symbols(text)
    context_symbols = tuple(str(item) for item in getattr(context, "last_symbols", ()) if item)
    symbols = explicit_symbols or context_symbols
    period = _resolve_period(text, context, received_at=received_at)
    comparison_requested = len(symbols) > 1 or any(token in normalized for token in ("\ube44\uad50", "\ube44\uaca8", "compare")) or getattr(context, "last_result_kind", "") == "symbol_comparison"
    inferred: dict[str, object] = {}
    provided: dict[str, object] = {}
    if explicit_symbols:
        provided["symbols"] = explicit_symbols
    elif symbols:
        inferred["symbols"] = symbols
    if period.requested_period:
        provided["period"] = period.requested_period
    requires_confirmation = not symbols or not period.start_date or not period.end_date
    return ConversationalResearchExecutionRequest(
        intent="research_rerun",
        symbols=tuple(dict.fromkeys(symbols)),
        requested_period=period.requested_period,
        start_date=period.start_date,
        end_date=period.end_date,
        reuse_previous_strategy=True,
        reuse_previous_assumptions=True,
        comparison_requested=comparison_requested,
        source_context_id=str(getattr(context, "created_at", "") or "") or None,
        user_provided_fields=provided,
        inferred_fields=inferred,
        requires_confirmation=requires_confirmation,
    )


def previous_request_text(context: Any, fallback: str) -> str:
    for payload in getattr(context, "last_structured_results", ()) or getattr(context, "last_payloads", ()):
        if isinstance(payload, dict) and isinstance(payload.get("request_text"), str):
            return str(payload["request_text"])
    return fallback


def render_research_execution_clarification(context: Any, text: str) -> str:
    symbols = tuple(str(item) for item in getattr(context, "last_symbols", ()) if item)
    labels = ", ".join(_symbol_label(symbol) for symbol in symbols) if symbols else "직전 종목"
    return "\n".join(
        [
            f"영하님, {labels}에 대한 재분석 요청으로 이해했습니다.",
            "다만 이번 요청에는 실제로 다시 검증할 기간이 충분히 명확하지 않습니다.",
            "예를 들어 `3년으로 다시 분석해줘`, `최근 5년으로 다시 분석해줘`, `2021년부터 지금까지 분석해줘`처럼 기간을 지정해 주세요.",
            "기간이 확인되기 전에는 기존 결과를 임의로 다시 계산하거나 조건을 바꾸지 않겠습니다.",
        ]
    )


def render_conversational_research_execution_result(result: ConversationalResearchExecutionResult) -> str:
    if result.execution_status != "success":
        return "영하님, 연구 재실행 결과를 안전하게 저장된 구조화 결과로 확인하지 못했습니다. 임의의 성과 숫자는 만들지 않겠습니다."
    if len(result.symbols) > 1:
        return _render_multi_symbol_result(result)
    return _render_single_symbol_result(result)


def _render_single_symbol_result(result: ConversationalResearchExecutionResult) -> str:
    payload = result.research_results[0]
    previous = result.previous_results[0] if result.previous_results else {}
    metrics = _metrics(payload)
    previous_metrics = _metrics(previous)
    metadata = _metadata(payload)
    quality = _quality(payload)
    symbol = result.symbols[0]
    lines = [
        f"영하님, {_symbol_label(symbol)}를 같은 전략 조건과 기존 가정으로 다시 분석했습니다.",
        "",
        "[재분석 범위]",
        f"- 기간: {result.resolved_start_date} ~ {result.resolved_end_date}",
        f"- 데이터 출처: {_source_label(metadata)}",
        f"- 데이터 품질: {quality.get('status', 'unknown')}",
        "",
        "[새 결과]",
        f"- 거래 수: {_fmt_int(metrics.get('trade_count'))}회",
        f"- 총수익률: {_fmt_percent(metrics.get('total_return'))}",
        f"- MDD: {_fmt_percent(metrics.get('mdd'))}",
        f"- 승률: {_fmt_percent(metrics.get('win_rate'))}",
        f"- Profit Factor: {_fmt_pf(metrics.get('profit_factor'))}",
    ]
    if previous_metrics:
        lines.extend(
            [
                "",
                "[직전 결과와 비교]",
                f"- 거래 수: {_fmt_int(previous_metrics.get('trade_count'))}회 → {_fmt_int(metrics.get('trade_count'))}회",
                f"- 총수익률: {_fmt_percent(previous_metrics.get('total_return'))} → {_fmt_percent(metrics.get('total_return'))}",
                f"- MDD: {_fmt_percent(previous_metrics.get('mdd'))} → {_fmt_percent(metrics.get('mdd'))}",
            ]
        )
    lines.extend(_quality_lines(result))
    lines.extend(["", "주문, Champion 자동 승격, 승인 없는 전략 설정 변경은 수행하지 않았습니다."])
    return "\n".join(lines)


def _render_multi_symbol_result(result: ConversationalResearchExecutionResult) -> str:
    if any(_symbol_from_payload(payload) == "unknown" or not _metrics(payload) for payload in result.research_results):
        return render_conversational_research_execution_result(
            ConversationalResearchExecutionResult(
                execution_status="invalid_result",
                symbols=result.symbols,
                resolved_start_date=result.resolved_start_date,
                resolved_end_date=result.resolved_end_date,
                research_results=(),
                previous_results=result.previous_results,
                comparison={},
                data_quality=(),
                limitations=(),
                execution_evidence=("invalid_multi_symbol_result",),
            )
        )
    lines = [
        "영하님, 직전 비교 대상 종목들을 같은 전략 조건과 기존 가정으로 다시 비교했습니다.",
        "",
        "[재분석 범위]",
        f"- 기간: {result.resolved_start_date} ~ {result.resolved_end_date}",
        "",
        "[종목별 결과]",
    ]
    for payload in result.research_results:
        symbol = _symbol_from_payload(payload)
        metrics = _metrics(payload)
        if not metrics and "symbols" in payload:
            lines.append(f"- {_symbol_label(symbol)}: 구조화된 성과 요약을 확인했습니다.")
            continue
        lines.append(
            f"- {_symbol_label(symbol)}: 거래 수 {_fmt_int(metrics.get('trade_count'))}회, "
            f"총수익률 {_fmt_percent(metrics.get('total_return'))}, MDD {_fmt_percent(metrics.get('mdd'))}"
        )
    if result.comparison:
        aggregate = result.comparison.get("aggregate_trade_count")
        confidence = result.comparison.get("sample_confidence")
        lines.extend(["", "[비교 요약]", f"- 전체 거래 수: {_fmt_int(aggregate)}회", f"- 표본 신뢰도: {confidence or 'unknown'}"])
    lines.extend(_quality_lines(result))
    lines.extend(["", "비교도 구조화된 safe tool 결과만 사용했으며, 주문이나 자동 승격은 수행하지 않았습니다."])
    return "\n".join(lines)


@dataclass(frozen=True)
class _ResolvedPeriod:
    requested_period: str | None
    start_date: str | None
    end_date: str | None


def _resolve_period(text: str, context: Any, *, received_at: str) -> _ResolvedPeriod:
    normalized = text.casefold()
    end_date = _context_end_date(context) or _date_from_received_at(received_at)
    if re.search(r"20\d{2}-\d{2}-\d{2}\s*[~\-]\s*20\d{2}-\d{2}-\d{2}", normalized):
        dates = re.findall(r"20\d{2}-\d{2}-\d{2}", normalized)
        return _ResolvedPeriod("explicit_range", dates[0], dates[1])
    start_year = re.search(r"(20\d{2})\s*(?:\ub144)?\s*(?:\ubd80\ud130|from)", normalized)
    if start_year is not None:
        return _ResolvedPeriod(f"{start_year.group(1)}-present", f"{start_year.group(1)}-01-01", end_date)
    year_match = re.search(r"(?:\ucd5c\uadfc\s*)?([1-9])\s*(?:\ub144|y|years?)", normalized)
    if year_match:
        years = int(year_match.group(1))
        return _ResolvedPeriod(f"{years}y", _years_before(end_date, years), end_date)
    year_match = re.search(r"(?<!\d)([1-9])\s*년", normalized)
    if year_match:
        years = int(year_match.group(1))
        return _ResolvedPeriod(f"{years}y", _years_before(end_date, years), end_date)
    if re.search(r"20\d{2}\s*년\s*부터", normalized):
        start_year = re.search(r"(20\d{2})\s*년\s*부터", normalized)
        if start_year is not None:
            return _ResolvedPeriod(f"{start_year.group(1)}-present", f"{start_year.group(1)}-01-01", end_date)
    if re.search(r"20\d{2}-\d{2}-\d{2}\s*[~\-]\s*20\d{2}-\d{2}-\d{2}", normalized):
        dates = re.findall(r"20\d{2}-\d{2}-\d{2}", normalized)
        return _ResolvedPeriod("explicit_range", dates[0], dates[1])
    return _ResolvedPeriod(None, None, None)


def _extract_symbols(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    mapping = (
        ("005930", ("005930", "삼성전자")),
        ("000660", ("000660", "sk하이닉스", "sk 하이닉스", "sk하이닏스")),
        ("005380", ("005380", "현대차")),
        ("035420", ("035420", "naver", "네이버")),
        ("051910", ("051910", "lg화학", "lg 화학")),
    )
    found: list[str] = []
    for symbol, aliases in mapping:
        if any(alias.casefold() in normalized for alias in aliases):
            found.append(symbol)
    for raw in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        if raw not in found:
            found.append(raw)
    return tuple(found)


def _context_end_date(context: Any) -> str | None:
    for payload in getattr(context, "last_structured_results", ()) or getattr(context, "last_payloads", ()):
        metadata = _metadata(payload)
        if isinstance(metadata.get("end_date"), str):
            return str(metadata["end_date"])
    return None


def _date_from_received_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).date().isoformat()
    except ValueError:
        return datetime.now(UTC).date().isoformat()


def _years_before(end_date: str, years: int) -> str:
    end = datetime.fromisoformat(end_date).date()
    try:
        start = end.replace(year=end.year - years) + timedelta(days=1)
    except ValueError:
        start = end.replace(year=end.year - years, day=28) + timedelta(days=1)
    return start.isoformat()


def _symbol_from_payload(payload: dict[str, object]) -> str:
    dataset = payload.get("dataset")
    if isinstance(dataset, dict):
        symbols = dataset.get("symbols")
        if isinstance(symbols, list) and symbols and isinstance(symbols[0], dict):
            return str(symbols[0].get("symbol", "unknown"))
    if payload.get("symbol") is not None:
        return str(payload["symbol"])
    return "unknown"


def _metrics(payload: dict[str, object]) -> dict[str, object]:
    backtest = payload.get("backtest")
    if isinstance(backtest, dict) and isinstance(backtest.get("metrics"), dict):
        return dict(backtest["metrics"])
    return {}


def _metadata(payload: dict[str, object]) -> dict[str, object]:
    dataset = payload.get("dataset")
    if isinstance(dataset, dict) and isinstance(dataset.get("metadata"), dict):
        return dict(dataset["metadata"])
    return {}


def _quality(payload: dict[str, object]) -> dict[str, object]:
    quality = payload.get("quality")
    return dict(quality) if isinstance(quality, dict) else {}


def _quality_lines(result: ConversationalResearchExecutionResult) -> list[str]:
    lines: list[str] = []
    warnings = tuple(item for item in result.limitations if item)
    if warnings:
        return [
            "",
            "[데이터 품질]",
            f"- 검증 경고 {len(warnings)}건이 있습니다. 요약 응답에서는 원시 증거를 전부 나열하지 않습니다.",
            "- 세부 날짜와 근거가 필요하면 '데이터 문제 자세히 보여줘'라고 말씀해 주세요.",
        ]
    return lines


def render_data_quality_details_from_payloads(payloads: tuple[dict[str, object], ...]) -> str:
    if not payloads:
        return "현재 저장된 연구 결과가 없어 데이터 품질 세부 내역을 보여드릴 수 없습니다."
    lines = ["데이터 품질 세부 내역입니다.", ""]
    for payload in payloads:
        symbol = _symbol_from_payload(payload)
        quality = _quality(payload)
        lines.append(f"[{_symbol_label(symbol)}]")
        lines.append(f"- 품질 상태: {quality.get('status', 'unknown')}")
        for key, label in (
            ("provider_gap_dates", "데이터 공급자 누락"),
            ("provider_ohlc_anomaly_dates", "데이터 공급자 OHLC 이상"),
            ("provider_zero_volume_anomaly_dates", "데이터 공급자 거래량 0 이상"),
            ("unknown_missing_trading_dates", "확인되지 않은 거래일 누락"),
            ("zero_volume_dates", "확인되지 않은 거래량 0"),
        ):
            values = quality.get(key)
            if isinstance(values, list) and values:
                lines.append(f"- {label}: {', '.join(str(item) for item in values[:20])}")
        findings = quality.get("findings")
        if isinstance(findings, list) and findings:
            lines.append("- 품질 finding:")
            for finding in findings[:10]:
                if isinstance(finding, dict):
                    code = finding.get("code", "unknown")
                    date = finding.get("date") or finding.get("trading_date") or finding.get("context", "")
                    message = finding.get("message", "")
                    lines.append(f"  - {code}: {date} {message}".rstrip())
        lines.append("")
    lines.append("위 내역은 저장된 구조화 결과에서만 읽었고, 연구 tool을 다시 실행하지 않았습니다.")
    return "\n".join(lines)


def _source_label(metadata: dict[str, object]) -> str:
    source = str(metadata.get("source", "unknown"))
    if source == "real:yahoo-chart":
        return "Yahoo Chart 공개 데이터"
    return source


def _symbol_label(symbol: str) -> str:
    return f"{_SYMBOL_LABELS.get(symbol, symbol)}({symbol})"


def _fmt_int(value: object) -> str:
    try:
        return str(int(float(str(value))))
    except (TypeError, ValueError):
        return "unknown"


def _fmt_percent(value: object) -> str:
    try:
        return f"{float(str(value)):.2%}"
    except (TypeError, ValueError):
        return "unknown"


def _fmt_pf(value: object) -> str:
    if value in (None, "None"):
        return "계산 불가"
    if str(value).casefold() == "inf":
        return "무한대"
    try:
        return f"{float(str(value)):.2f}"
    except (TypeError, ValueError):
        return "unknown"
