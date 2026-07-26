"""Grounded research response helpers for conversational safe tools."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


RESEARCH_TOOLS = {
    "research_memory_search",
    "strategy_critique",
    "strategy_quality_score",
    "research_candidate_compare",
    "research_lineage",
    "market_data_status",
    "dataset_lookup",
    "data_quality_check",
    "backtest_strategy",
    "backtest_result",
    "compare_backtests",
    "krx_market_data",
    "krx_real_research",
    "research_retest",
}

FIXTURE_LEAKAGE_TOKENS = (
    "1.5x",
    "volume_multiplier",
    "volume multiplier",
    "max_risk_pct=1.0",
    "max_risk_pct",
    "regime_tags",
)

FABRICATED_METRIC_TOKENS = (
    "1.35",
    "1.05",
    "64",
    "520",
    "14%",
    "0.14",
    "\uc0e4\ud504 1.35",
    "\uc0e4\ud504 1.05",
    "MDD 14",
    "\uac70\ub798 64",
    "\uc0d8\ud50c 520",
    *FIXTURE_LEAKAGE_TOKENS,
)

WRAPPER_TAG_PATTERN = re.compile(r"</?(?:output|response)>", re.IGNORECASE)

CRITIQUE_TRANSLATIONS = {
    "In-sample performance is much stronger than out-of-sample performance.": "\ud45c\ubcf8 \ub0b4 \uc131\uacfc\uac00 \ud45c\ubcf8 \uc678 \uc131\uacfc\ubcf4\ub2e4 \ud06c\uac8c \ub192\uc2b5\ub2c8\ub2e4.",
    "Parameter sensitivity is high.": "\ud30c\ub77c\ubbf8\ud130 \ubbfc\uac10\ub3c4\uac00 \ub192\uc2b5\ub2c8\ub2e4.",
    "Feature complexity is high relative to evidence quality.": "\ud604\uc7ac \uac80\uc99d \uadfc\uac70\uc5d0 \ube44\ud574 \uc804\ub7b5\uc758 \ud2b9\uc9d5/\uc870\uac74 \ubcf5\uc7a1\ub3c4\uac00 \ub192\uc2b5\ub2c8\ub2e4.",
}

ACTION_TRANSLATIONS = {
    "Reduce parameter freedom and require walk-forward confirmation.": "\ud30c\ub77c\ubbf8\ud130 \uc790\uc720\ub3c4\ub97c \uc904\uc774\uace0 \uc6cc\ud06c\ud3ec\uc6cc\ub4dc \uac80\uc99d\uc744 \uc694\uad6c\ud558\ub294 \uac83\uc774 \uc88b\uc2b5\ub2c8\ub2e4.",
    "Prefer wider robust ranges over narrow optimized values.": "\uc881\uac8c \ucd5c\uc801\ud654\ub41c \uac12\ubcf4\ub2e4 \ub354 \ub113\uace0 \uacac\uace0\ud55c \ubc94\uc704\ub97c \uc6b0\uc120\ud558\ub294 \uac83\uc774 \uc88b\uc2b5\ub2c8\ub2e4.",
    "Remove low-contribution features.": "\uae30\uc5ec\ub3c4\uac00 \ub0ae\uc740 \uc870\uac74\uc740 \uc81c\uac70\ud558\uac70\ub098 \ubcc4\ub3c4\ub85c \uac80\uc99d\ud558\ub294 \uac83\uc774 \uc88b\uc2b5\ub2c8\ub2e4.",
}


@dataclass(frozen=True)
class ResearchFact:
    name: str
    value: object
    source: str
    source_ref: str


def is_research_tool(tool_name: str) -> bool:
    return tool_name in RESEARCH_TOOLS


def is_korean_request(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in text)


def contains_unverified_fixture_metrics(text: str, facts: Iterable[ResearchFact] = ()) -> bool:
    allowed = {str(fact.value) for fact in facts}
    return any(token in text and token not in allowed for token in FABRICATED_METRIC_TOKENS)


def contains_fixture_leakage(text: str) -> bool:
    return any(token in text for token in FIXTURE_LEAKAGE_TOKENS)


def contains_wrapper_tags(text: str) -> bool:
    return bool(WRAPPER_TAG_PATTERN.search(text))


def strip_response_wrappers(text: str) -> str:
    return WRAPPER_TAG_PATTERN.sub("", text).strip()


def looks_like_english_final(text: str) -> bool:
    stripped = strip_response_wrappers(text)
    letters = sum(1 for char in stripped if ("a" <= char.lower() <= "z"))
    hangul = sum(1 for char in stripped if "\uac00" <= char <= "\ud7a3")
    return letters >= 24 and hangul == 0


def normalize_final_response(text: str, user_text: str) -> str:
    cleaned = strip_response_wrappers(text)
    if is_korean_request(user_text) and looks_like_english_final(cleaned):
        return (
            "\uc601\ud558\ub2d8, \ud55c\uad6d\uc5b4 \uc9c8\ubb38\uc73c\ub85c \uc774\ud574\ud588\uc2b5\ub2c8\ub2e4. "
            "\ud604\uc7ac \uac80\uc99d\ub41c \uadfc\uac70\uac00 \ucda9\ubd84\ud558\uc9c0 \uc54a\uc544 \uc784\uc758\uc758 \uacb0\uacfc\ub97c \ub9cc\ub4e4\uc9c0 \uc54a\uaca0\uc2b5\ub2c8\ub2e4."
        )
    return cleaned


def grounded_system_policy() -> str:
    return (
        "For research or strategy claims, use only user-provided facts or verified safe-tool results. "
        "Never invent Sharpe, MDD, trade count, sample size, dates, backtest metrics, fixture parameters, or regime tags. "
        "Do not present fixture/default candidate metadata as the current user strategy. "
        "If a metric is unavailable, say it is unavailable. "
        "If the user writes Korean, the final user-facing answer must be natural Korean and must not expose output/response XML tags. "
        "Separate verified data, qualitative analysis, and hypotheses. "
        "Disclose fixture-backed data as fixtures and do not label it real historical data."
    )


def extract_user_strategy_context(text: str) -> dict[str, object]:
    conditions: list[str] = []
    normalized = text.casefold()
    if "20" in text and ("\uace0\uac00" in text or "high" in normalized) and ("\ub3cc\ud30c" in text or "breakout" in normalized):
        conditions.append("20\uc77c \uace0\uac00 \ub3cc\ud30c")
    if ("\uc885\uac00" in text or "close" in normalized) and ("ma20" in normalized or "20" in text) and ("ma60" in normalized or "60" in text):
        conditions.append("\uc885\uac00 > MA20 > MA60")
    if "\uac70\ub798\ub7c9" in text and ("20\uc77c" in text or "\ud3c9\uade0" in text):
        conditions.append("\uac70\ub798\ub7c9 >= 20\uc77c \ud3c9\uade0")
    if "\uc190\uc808" in text and ("-5" in text or "5%" in text):
        conditions.append("\uc190\uc808 -5%")
    if "10\uc77c" in text and ("\uc800\uc810" in text or "low" in normalized) and ("\uccad\uc0b0" in text or "\uc774\ud0c8" in text):
        conditions.append("10\uc77c \uc800\uc810 \uc774\ud0c8 \uccad\uc0b0")
    return {"source": "user_provided", "conditions": conditions}


def sanitize_research_tool_output(tool_name: str, output: dict[str, object], user_text: str = "") -> dict[str, object]:
    if tool_name == "strategy_critique":
        return {
            "provider": output.get("provider", "unknown"),
            "fixture_backed": str(output.get("provider", "")).startswith("fixture:"),
            "user_strategy_context": extract_user_strategy_context(user_text),
            "critique": _safe_critique(output.get("critique")),
            "improvement_plan": _safe_plan(output.get("improvement_plan")),
            "fixture_candidate_internals_removed": True,
            "automatic_promotion": False,
        }
    if tool_name == "strategy_quality_score" and str(output.get("provider", "")).startswith("fixture:"):
        return {
            "provider": output.get("provider", "unknown"),
            "fixture_backed": True,
            "quality_score_available": False,
            "message": "No actual backtest-based quality score is stored for the current user strategy.",
            "fixture_candidate_internals_removed": True,
            "automatic_promotion": False,
        }
    return dict(output)


def format_grounded_tool_response(tool_name: str, output: dict[str, object], user_text: str = "") -> str | None:
    if tool_name == "krx_real_research":
        return _format_krx_real_research(output)
    if tool_name == "research_retest":
        return _format_research_retest(output)
    if tool_name == "research_memory_search":
        return _format_memory(output)
    if tool_name == "strategy_critique":
        return _format_strategy_critique(output, user_text)
    if tool_name == "strategy_quality_score":
        return _format_quality(output)
    if tool_name == "data_quality_check":
        return _format_data_quality(output)
    if tool_name == "backtest_strategy":
        return _format_backtest(output.get("result"))
    if tool_name == "backtest_result":
        return _format_backtest(output.get("result"))
    if tool_name == "compare_backtests":
        return _format_comparison(output)
    return None


def is_strict_real_research_tool(tool_name: str) -> bool:
    return tool_name in {"krx_real_research", "research_retest"}


def contains_ungrounded_real_research_claim(text: str, output: dict[str, object]) -> bool:
    return bool(strict_real_research_grounding_violations(text, output))


def strict_real_research_grounding_violations(text: str, output: dict[str, object]) -> tuple[str, ...]:
    """Return fail-closed grounding violations for user-facing real research text."""
    if _is_retest_output(output):
        return _strict_retest_grounding_violations(text, output)
    allowed = _strict_real_research_allowed_tokens(output)
    suspicious = (
        "fixed risk=1.0",
        "risk 1.0",
        "daily rebalance",
        "0.5%",
        "take profit 3",
        "take-profit 3",
        "take profit 5",
        "take-profit 5",
        "RSI 20",
        "RSI 30",
        "RSI(14) 30",
        "MA15",
        "MA90",
        "volume 1.5",
        "volume_multiplier",
        "1.5x",
        "-3% stop",
        "-3% 손절",
        "5% 익절",
        "10일 기간",
        "10-day",
    )
    violations = [f"ungrounded_token:{token}" for token in suspicious if token in text and token not in allowed]
    authoritative_trade_counts = _authoritative_trade_counts(output)
    if authoritative_trade_counts:
        for reported in _reported_trade_counts(text):
            if reported not in authoritative_trade_counts:
                expected = "/".join(str(value) for value in sorted(authoritative_trade_counts))
                violations.append(f"trade_count_mismatch:{reported}!={expected}")
    for metric_name, reported in _reported_authoritative_alias_metrics(text):
        expected_values = _authoritative_metric_numeric_values(output, metric_name)
        if not expected_values:
            violations.append(f"{metric_name}_missing_authoritative_evidence:{_trim_float(reported)}")
        elif not any(_metric_numbers_match(reported, expected) for expected in expected_values):
            expected = "/".join(_trim_float(value) for value in sorted(expected_values))
            violations.append(f"{metric_name}_mismatch:{_trim_float(reported)}!={expected}")
    hypothesis = _section_after(text, "HYPOTHESIS")
    if hypothesis and _contains_performance_number(hypothesis):
        violations.append("hypothesis_contains_performance_metric")
    return tuple(dict.fromkeys(violations))


def _format_memory(output: dict[str, object]) -> str:
    count = int(output.get("count", 0) or 0)
    if count <= 0:
        return (
            "\uc601\ud558\ub2d8, \uc5f0\uad6c \uba54\ubaa8\ub9ac\ub97c \uac80\uc0c9\ud588\uc9c0\ub9cc \uc800\uc7a5\ub41c \uc720\uc0ac \uc5f0\uad6c \uae30\ub85d\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.\n"
            "\uac80\uc99d\ub41c \ub370\uc774\ud130: \uac80\uc0c9 \ub3c4\uad6c\ub294 \uc815\uc0c1 \ub3d9\uc791\ud588\uace0 \uacb0\uacfc \uc218\ub294 0\uac74\uc785\ub2c8\ub2e4.\n"
            "\uc815\uc131 \ubd84\uc11d: \uc544\uc9c1 \uc800\uc7a5\ub41c \ub9e4\uce6d \uae30\ub85d\uc774 \uc5c6\ub2e4\ub294 \ub73b\uc785\ub2c8\ub2e4.\n"
            "\uac00\uc124/\uc81c\uc548: \ud604\uc7ac \uc804\ub7b5 \uc870\uac74\uc744 \uae30\uc900\uc73c\ub85c \uc0c8 \uc5f0\uad6c \uae30\ub85d\uc744 \ub9cc\ub4e4\uac70\ub098 \ubc31\ud14c\uc2a4\ud2b8 \uacb0\uacfc\ub97c \uba3c\uc800 \uc5f0\uacb0\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        )
    results = output.get("results")
    lines = [f"\uc601\ud558\ub2d8, \uc800\uc7a5\ub41c \uc5f0\uad6c \uba54\ubaa8\ub9ac\uc5d0\uc11c {count}\uac74\uc744 \ucc3e\uc558\uc2b5\ub2c8\ub2e4.", "\uac80\uc99d\ub41c \ub370\uc774\ud130:"]
    if isinstance(results, list):
        for item in results[:3]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('memory_id') or item.get('run_id') or 'memory'} / {item.get('strategy_family') or item.get('family') or 'unknown'}")
    lines.append("\uc815\uc131 \ubd84\uc11d: \uc704 \ud56d\ubaa9\uc740 \uc800\uc7a5\ub41c \uc5f0\uad6c \uae30\uc5b5\uc744 \uae30\uc900\uc73c\ub85c\ub9cc \uc694\uc57d\ud588\uc2b5\ub2c8\ub2e4.")
    return "\n".join(lines)


def _format_research_retest(output: dict[str, object]) -> str:
    report = str(output.get("korean_report") or "").strip()
    if report:
        return strip_response_wrappers(report)
    evidence = _as_list(output.get("evidence"))
    lines = [
        "[자동 재검증 결과]",
        f"- stop_reason={output.get('stop_reason', 'unknown')}",
        f"- recommendation={output.get('final_recommendation', 'unknown')}",
        "- 자동 주문/KIS 주문/Broker 주문/Champion 자동 승격/승인 없는 config 변경은 수행하지 않았습니다.",
        "",
        "[기간별 증거]",
    ]
    for item in evidence:
        data = _as_dict(item)
        period = _as_dict(data.get("period"))
        lines.append(
            f"- {period.get('label', 'period')}: {period.get('start_date', 'unknown')}~{period.get('end_date', 'unknown')} "
            f"trade_count={data.get('trade_count', 'unknown')} quality={data.get('quality_status', 'unknown')} confidence={data.get('confidence_level', 'unknown')}"
        )
    return "\n".join(lines)


def _format_krx_real_research(output: dict[str, object]) -> str:
    dataset = _as_dict(output.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    quality = _as_dict(output.get("quality"))
    backtest = _as_dict(output.get("backtest"))
    metrics = _as_dict(backtest.get("metrics"))
    validation = _as_dict(output.get("validation"))
    strategy = _as_dict(output.get("strategy"))
    assumptions = _as_dict(output.get("assumptions"))
    comparison = _as_dict(output.get("comparison"))
    rows = _as_list(comparison.get("rows"))
    findings = _as_list(output.get("critic_findings"))
    candidates = _as_list(output.get("candidates"))
    provider_gap_dates = _quality_finding_dates(quality, "provider_gap")
    lines = [
        "영하님, 실제 KRX 연구 결과는 구조화된 백테스트 결과만 기준으로 정리하겠습니다.",
        "",
        "[데이터]",
        f"- 종목: {_symbol_label(dataset)}",
        f"- provider={metadata.get('source', 'unknown')}",
        f"- 기간={metadata.get('start_date', 'unknown')} ~ {metadata.get('end_date', 'unknown')}",
        f"- bars={len(_as_list(dataset.get('bars')))}",
        f"- source={backtest.get('source', 'unknown')}",
        f"- fixture_backed={str(metadata.get('fixture_backed', 'unknown')).lower()}",
        f"- quality_status={quality.get('status', 'unknown')}",
    ]
    if provider_gap_dates:
        lines.append(f"- provider_gap_dates={', '.join(provider_gap_dates)}")
        lines.append(f"- 공급자 경고: 실제 KRX 거래일 {', '.join(provider_gap_dates)} 일봉이 provider에서 누락된 것으로 분류했습니다.")
    lines.extend(
        [
            "",
            "[전략 조건 - user_provided]",
            *_strategy_lines(strategy),
            "",
            "[백테스트 가정 - engine/default]",
            *_assumption_lines(assumptions),
            "",
            "[백테스트 결과 - BacktestResult]",
            *_metric_lines(metrics),
            "",
            "[검증 - ValidationReport]",
            f"- validation_id={validation.get('validation_id', 'unknown')}",
            f"- passed={validation.get('passed', 'unknown')}",
        ]
    )
    validation_findings = _as_list(validation.get("findings"))
    if validation_findings:
        lines.extend(f"- finding={item}" for item in validation_findings)
    lines.extend(["", "[약점 - EvidenceBasedCritic]"])
    if findings:
        for finding in findings:
            item = _as_dict(finding)
            lines.append(f"- {item.get('severity', 'unknown')}: {item.get('message_ko', item.get('code', 'finding'))}")
    else:
        lines.append("- 저장된 critic finding이 없습니다.")
    lines.extend(["", "[개선 후보 - TESTED]"])
    tested = False
    for candidate in candidates:
        item = _as_dict(candidate)
        result = _as_dict(item.get("backtest_result"))
        if not result:
            continue
        tested = True
        candidate_metrics = _as_dict(result.get("metrics"))
        lines.append(
            "- TESTED "
            f"{item.get('candidate_id', 'candidate')}: "
            f"trade_count={candidate_metrics.get('trade_count', 'unknown')} "
            f"total_return={candidate_metrics.get('total_return', 'unknown')} "
            f"mdd={candidate_metrics.get('mdd', 'unknown')}"
        )
    if not tested:
        lines.append("- TESTED 후보가 없습니다. 검증되지 않은 후보를 검증 완료처럼 말하지 않겠습니다.")
    lines.extend(["", "[후보 비교 - CandidateComparison]"])
    if rows:
        for row in rows:
            item = _as_dict(row)
            lines.append(
                f"- {item.get('candidate_id', 'candidate')}: "
                f"total_return={item.get('total_return', 'unknown')} "
                f"mdd={item.get('mdd', 'unknown')} "
                f"trade_count={item.get('trade_count', 'unknown')}"
            )
    else:
        lines.append("- 비교 결과가 저장되어 있지 않습니다.")
    lines.extend(
        [
            "",
            "[추가 검증 아이디어 - HYPOTHESIS]",
            "- 리스크 축소, 익절 조건, RSI 필터, 거래량 배수 변경은 현재 결과에서 검증된 값이 아닙니다. 별도 후보를 만들고 동일한 dataset/assumptions로 백테스트해야 합니다.",
            "",
            "[가온의 판단]",
            "- 위 숫자는 user input, dataset metadata, DataQualityReport, BacktestResult, ValidationReport, tested ImprovementCandidate, CandidateComparison에 존재하는 필드만 사용했습니다.",
            "- 자동 주문, KIS 주문, Champion 자동 승격, 승인 우회는 수행하지 않았습니다.",
        ]
    )
    return "\n".join(lines)


def _format_strategy_critique(output: dict[str, object], user_text: str) -> str:
    safe = sanitize_research_tool_output("strategy_critique", output, user_text)
    critique = safe.get("critique")
    plan = safe.get("improvement_plan")
    context = safe.get("user_strategy_context")
    provider = safe.get("provider", "unknown")
    lines = [
        "\uc601\ud558\ub2d8, \uc774 \uc804\ub7b5\uc740 \uc0ac\uc6a9\uc790\ub2d8\uc774 \uc81c\uacf5\ud55c \uc870\uac74\uacfc fixture/default \ud6c4\ubcf4 \uc815\ubcf4\ub97c \ubd84\ub9ac\ud574\uc11c \ubcf4\uaca0\uc2b5\ub2c8\ub2e4.",
        "\uac80\uc99d\ub41c \ub370\uc774\ud130:",
        f"- data_source={provider}",
        "- fixture_backed=true",
        "- field_provenance=user_provided conditions only; fixture candidate internals are excluded.",
    ]
    if isinstance(context, dict):
        conditions = context.get("conditions")
        if isinstance(conditions, list) and conditions:
            lines.append("- user_provided_conditions=" + ", ".join(str(item) for item in conditions))
        else:
            lines.append("- user_provided_conditions=not_structured")
    lines.extend(("- \uc2e4\uc81c \ubc31\ud14c\uc2a4\ud2b8 \uc131\uacfc \uc9c0\ud45c\ub294 \uc774 \uc751\ub2f5\uc5d0\uc11c \ud655\uc778\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.", "\uc815\uc131 \ubd84\uc11d:"))
    if isinstance(critique, dict):
        findings = critique.get("findings")
        if isinstance(findings, list) and findings:
            for finding in findings[:4]:
                if isinstance(finding, dict):
                    message = _ko(finding.get("message", "finding"))
                    severity = finding.get("severity", "unknown")
                    lines.append(f"- {severity}: {message}")
    lines.append("\uac00\uc124/\uac1c\uc120 \uc81c\uc548:")
    if isinstance(plan, dict):
        actions = plan.get("actions")
        if isinstance(actions, list) and actions:
            for action in actions[:4]:
                if isinstance(action, dict):
                    default_description = "\uac80\uc99d \uc870\uac74\uc744 \ubcf4\uc644\ud569\ub2c8\ub2e4."
                    description = action.get("description", default_description)
                    lines.append(f"- {_ko(description)}")
    if lines[-1] == "\uac00\uc124/\uac1c\uc120 \uc81c\uc548:":
        lines.append("- \uc2e4\uc81c \ub370\uc774\ud130 \ubc31\ud14c\uc2a4\ud2b8, \uc6cc\ud06c\ud3ec\uc6cc\ub4dc, \ube44\uc6a9 \uac00\uc815 \uac80\uc99d\uc744 \uba3c\uc800 \uc5f0\uacb0\ud558\ub294 \uac83\uc774 \uc548\uc804\ud569\ub2c8\ub2e4.")
    lines.append("fixture\uc758 \uae30\ubcf8 \ud30c\ub77c\ubbf8\ud130\ub098 regime \ud0dc\uadf8\ub97c \ud604\uc7ac \uc0ac\uc6a9\uc790 \uc804\ub7b5\uc758 \uac12\ucc98\ub7fc \uc0ac\uc6a9\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.")
    lines.append("\uc790\ub3d9 \uc2b9\uc778\uc774\ub098 Champion \uc2b9\uaca9\uc740 \uc218\ud589\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.")
    return "\n".join(lines)


def _format_quality(output: dict[str, object]) -> str:
    provider = output.get("provider", "unknown")
    if str(provider).startswith("fixture:"):
        return (
            "\uc601\ud558\ub2d8, \ud604\uc7ac \uc774 \uc804\ub7b5\uc5d0 \ub300\ud574 \uc2e4\uc81c \ubc31\ud14c\uc2a4\ud2b8\ub97c \uae30\ubc18\uc73c\ub85c \uacc4\uc0b0\ub41c \uc5f0\uad6c \ud488\uc9c8 \uc810\uc218\ub294 \uc800\uc7a5\ub418\uc5b4 \uc788\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. "
            "\ub530\ub77c\uc11c \uc784\uc758\uc758 \uc810\uc218\ub97c \uc0dd\uc131\ud558\uc9c0 \uc54a\uaca0\uc2b5\ub2c8\ub2e4.\n"
            "\uac80\uc99d\ub41c \ub370\uc774\ud130:\n"
            f"- data_source={provider}\n"
            "- fixture_backed=true\n"
            "- quality_score_available=false\n"
            "\uc815\uc131 \ubd84\uc11d: fixture/default \ud6c4\ubcf4\uc758 \ud488\uc9c8 \uc810\uc218\ub97c \ud604\uc7ac \uc0ac\uc6a9\uc790 \uc804\ub7b5\uc758 \uc810\uc218\ucc98\ub7fc \uc0ac\uc6a9\ud558\uc9c0 \uc54a\uaca0\uc2b5\ub2c8\ub2e4.\n"
            "\uac00\uc124/\uc81c\uc548: \uc2e4\uc81c \uc2dc\uc7a5 \ub370\uc774\ud130 \ubc31\ud14c\uc2a4\ud2b8\uac00 \uc644\ub8cc\ub418\uba74 \ud574\ub2f9 \uacb0\uacfc\ub97c \uae30\ubc18\uc73c\ub85c \ud488\uc9c8 \uc810\uc218\ub97c \uacc4\uc0b0\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        )
    quality = output.get("quality")
    lines = ["\uc601\ud558\ub2d8, \uc804\ub7b5 \ud488\uc9c8 \uc810\uc218\ub294 \ub3c4\uad6c\uac00 \ubc18\ud658\ud55c \ud488\uc9c8 \ud544\ub4dc\ub9cc \uc0ac\uc6a9\ud574 \uc124\uba85\ud558\uaca0\uc2b5\ub2c8\ub2e4.", "\uac80\uc99d\ub41c \ub370\uc774\ud130:", f"- data_source={provider}"]
    if isinstance(quality, dict):
        total = quality.get("total")
        if total is not None:
            lines.append(f"- total={total}")
        components = quality.get("components")
        if isinstance(components, dict):
            for key in sorted(components)[:10]:
                lines.append(f"- {key}={components[key]}")
    lines.extend(("\uc815\uc131 \ubd84\uc11d: \uc704 \uc810\uc218\ub294 \ud488\uc9c8 \uc2a4\ucf54\uc5b4 \uacc4\uc57d\uc758 \uad6c\uc131 \uc694\uc18c\uc774\uba70, \ubcc4\ub3c4 \ubc31\ud14c\uc2a4\ud2b8 \uc131\uacfc \uc218\uce58\ub85c \ud574\uc11d\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.", "\uac00\uc124/\uc81c\uc548: \ub0ae\uc740 \uad6c\uc131 \uc694\uc18c\ubd80\ud130 \uac80\uc99d \uacc4\ud68d\uc744 \uc138\uc6b0\ub418 \uc790\ub3d9 \uc2b9\uaca9\uc740 \ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."))
    return "\n".join(lines)


def _format_data_quality(output: dict[str, object]) -> str:
    dataset = output.get("dataset")
    quality = output.get("quality")
    dataset_id = "unknown"
    fixture_backed = "unknown"
    source = "unknown"
    if isinstance(dataset, dict):
        dataset_id = str(dataset.get("dataset_id", "unknown"))
        metadata = dataset.get("metadata")
        if isinstance(metadata, dict):
            fixture_backed = str(metadata.get("fixture_backed", "unknown")).lower()
            source = str(metadata.get("source", "unknown"))
    status = quality.get("status", "unknown") if isinstance(quality, dict) else "unknown"
    return (
        "\uc601\ud558\ub2d8, \ub370\uc774\ud130 \ud488\uc9c8 \ud655\uc778 \uacb0\uacfc\uc785\ub2c8\ub2e4.\n"
        "\uac80\uc99d\ub41c \ub370\uc774\ud130:\n"
        f"- dataset_id={dataset_id}\n"
        f"- data_source={source}\n"
        f"- fixture_backed={fixture_backed}\n"
        f"- quality_status={status}\n"
        "\uc815\uc131 \ubd84\uc11d: fixture_backed=true\uc774\uba74 \uc2e4\uc81c \uc2dc\uc7a5 \ub370\uc774\ud130\uac00 \uc544\ub2c8\ub77c \ud14c\uc2a4\ud2b8 fixture\uc785\ub2c8\ub2e4.\n"
        "\uac00\uc124/\uc81c\uc548: \uc2e4\ub370\uc774\ud130 \uc5f0\uacb0 \uc804\uc5d0\ub294 \uc774 \uacb0\uacfc\ub97c \uc6b4\uc601 \uc131\uacfc\ub85c \ud574\uc11d\ud558\uc9c0 \uc54a\ub294 \uac83\uc774 \uc548\uc804\ud569\ub2c8\ub2e4."
    )


def _format_backtest(result_obj: object) -> str:
    if not isinstance(result_obj, dict):
        return "\uc601\ud558\ub2d8, \uc694\uccad\ud55c \ubc31\ud14c\uc2a4\ud2b8 \uacb0\uacfc\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uc800\uc7a5\ub41c \uacb0\uacfc ID\ub97c \ub2e4\uc2dc \ud655\uc778\ud574 \uc8fc\uc138\uc694."
    metrics = result_obj.get("metrics")
    provenance = result_obj.get("provenance")
    source = result_obj.get("source", "unknown")
    lines = ["\uc601\ud558\ub2d8, \ubc31\ud14c\uc2a4\ud2b8 \uacb0\uacfc\ub294 \ubc18\ud658\ub41c \uacb0\uacfc \uac1d\uccb4\uc758 \uc218\uce58\ub9cc \uc0ac\uc6a9\ud574 \uc694\uc57d\ud558\uaca0\uc2b5\ub2c8\ub2e4.", "\uac80\uc99d\ub41c \ub370\uc774\ud130:", f"- validation_backend={source}"]
    if isinstance(provenance, dict):
        lines.append(f"- dataset_id={provenance.get('dataset_id', 'unknown')}")
        lines.append(f"- fixture_backed={str(provenance.get('fixture_backed', 'unknown')).lower()}")
    if isinstance(metrics, dict):
        for key in ("total_return", "cagr", "mdd", "win_rate", "profit_factor", "trade_count", "expectancy", "sharpe"):
            if key in metrics:
                lines.append(f"- {key}={metrics[key]}")
    lines.extend(("\uc815\uc131 \ubd84\uc11d: fixture_backed=true\uc774\uba74 \uc2e4\uc81c \uc2dc\uc7a5 \uc131\uacfc\uac00 \uc544\ub2c8\ub77c deterministic fixture \uac80\uc99d\uc785\ub2c8\ub2e4.", "\uac00\uc124/\uc81c\uc548: \uc2e4\ub370\uc774\ud130, \ube44\uc6a9, \uc6cc\ud06c\ud3ec\uc6cc\ub4dc, \ubaac\ud14c\uce74\ub97c\ub85c \uac80\uc99d \uc804\uc5d0\ub294 Champion \uc2b9\uaca9 \uadfc\uac70\ub85c \uc0ac\uc6a9\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."))
    return "\n".join(lines)


def _format_comparison(output: dict[str, object]) -> str:
    comparison = output.get("comparison")
    lines = ["\uc601\ud558\ub2d8, \ube44\uad50 \uacb0\uacfc\ub294 \ub3c4\uad6c\uac00 \ubc18\ud658\ud55c delta \ud544\ub4dc\ub9cc \uae30\uc900\uc73c\ub85c \uc815\ub9ac\ud569\ub2c8\ub2e4.", "\uac80\uc99d\ub41c \ub370\uc774\ud130:"]
    if isinstance(comparison, dict):
        deltas = comparison.get("metric_deltas")
        if isinstance(deltas, dict):
            for key in sorted(deltas):
                lines.append(f"- {key}_delta={deltas[key]}")
        winner = comparison.get("winner")
        if winner is not None:
            lines.append(f"- winner={winner}")
    lines.append("\uc815\uc131 \ubd84\uc11d: \uc774 \ube44\uad50\ub294 fixture \uacc4\uc57d \uac80\uc99d\uc774\uba70 \uc790\ub3d9 \uc2b9\uc778\uc774\ub098 \ubc30\ud3ec\ub97c \uc218\ud589\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.")
    return "\n".join(lines)


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _symbol_label(dataset: dict[str, object]) -> str:
    symbols = _as_list(dataset.get("symbols"))
    if symbols:
        first = _as_dict(symbols[0])
        return str(first.get("symbol", "unknown"))
    return "unknown"


def _strategy_lines(strategy: dict[str, object]) -> list[str]:
    lines: list[str] = []
    labels = {
        "breakout_lookback": "20일 고가 돌파",
        "close_gt_ma20": "종가 > MA20",
        "ma20_gt_ma60": "MA20 > MA60",
        "volume_gte_ma20": "거래량 >= 20일 평균",
        "protective_stop_pct": "손절",
        "channel_exit_lookback": "10일 저점 이탈 청산",
    }
    for section_name, section in (("entry", strategy.get("entry")), ("exit", strategy.get("exit")), ("filters", strategy.get("filters"))):
        if not isinstance(section, dict):
            continue
        for key in sorted(section):
            value = _as_dict(section[key])
            provenance = value.get("provenance", "unknown")
            raw_value = value.get("value")
            label = labels.get(str(key), str(key))
            if str(key) == "protective_stop_pct" and raw_value is not None:
                label = f"손절 {raw_value}%"
            if provenance == "user_provided":
                lines.append(f"- {label}: {section_name}.{key}={raw_value} provenance=user_provided")
            else:
                lines.append(f"- {label}: {section_name}.{key}=not_user_provided provenance={provenance}")
    return lines or ["- user_provided 전략 조건을 구조화하지 못했습니다."]


def _assumption_lines(assumptions: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key in sorted(assumptions):
        value = _as_dict(assumptions[key])
        lines.append(f"- {key}={value.get('value', 'unknown')} provenance={value.get('provenance', 'unknown')}")
    return lines or ["- 백테스트 가정이 저장되어 있지 않습니다."]


def _metric_lines(metrics: dict[str, object]) -> list[str]:
    keys = ("total_return", "cagr", "mdd", "max_drawdown", "sharpe", "win_rate", "profit_factor", "trade_count", "trades", "wins", "win", "losses", "loss", "average_trade", "average_win", "average_loss", "expectancy", "exposure", "ending_equity")
    lines = [f"- {key}={metrics[key]}" for key in keys if key in metrics]
    return lines or ["- BacktestResult metrics가 저장되어 있지 않습니다."]


def _quality_finding_dates(quality: dict[str, object], code: str) -> tuple[str, ...]:
    dates = []
    for finding in _as_list(quality.get("findings")):
        item = _as_dict(finding)
        if item.get("code") != code:
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(item.get("message", "")))
        if match:
            dates.append(match.group(0))
    return tuple(dates)


def _is_retest_output(output: dict[str, object]) -> bool:
    return "stop_reason" in output and "evidence" in output and "final_recommendation" in output


def _strict_retest_grounding_violations(text: str, output: dict[str, object]) -> tuple[str, ...]:
    evidence_counts = {int(item.get("trade_count", -1)) for item in (_as_dict(raw) for raw in _as_list(output.get("evidence"))) if "trade_count" in item}
    candidate_counts = set()
    for candidate in _as_list(output.get("candidates")):
        result = _as_dict(_as_dict(candidate).get("backtest_result"))
        metrics = _as_dict(result.get("metrics"))
        if "trade_count" in metrics:
            candidate_counts.add(int(metrics["trade_count"]))
    allowed_counts = evidence_counts | candidate_counts
    violations: list[str] = []
    for match in re.finditer(r"(?:trade_count|trades|거래\s*수)\s*[=:]?\s*(\d+)", text, flags=re.IGNORECASE):
        value = int(match.group(1))
        if value not in allowed_counts:
            violations.append(f"retest_trade_count_not_authoritative:{value}")
    if any(token in text for token in ("자동 승격했습니다", "자동승격했습니다", "주문 실행했습니다", "KIS 주문 실행", "Broker 주문 실행")):
        violations.append("retest_forbidden_action_claim")
    return tuple(violations)


def _strict_real_research_allowed_tokens(output: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    tokens.update(_quality_finding_dates(_as_dict(output.get("quality")), "provider_gap"))
    tokens.update(_authoritative_metric_tokens(output))
    return tokens


_METRIC_ALIASES = {
    "trade_count": ("trade_count", "trades", "거래 횟수", "거래"),
    "trades": ("trade_count", "trades", "거래 횟수", "거래"),
    "wins": ("wins", "win", "승리", "승리 거래", "수익 거래"),
    "win": ("wins", "win", "승리", "승리 거래", "수익 거래"),
    "losses": ("losses", "loss", "패배", "손실 거래"),
    "loss": ("losses", "loss", "패배", "손실 거래"),
    "mdd": ("mdd", "MDD", "max_drawdown", "최대 낙폭"),
    "max_drawdown": ("mdd", "MDD", "max_drawdown", "최대 낙폭"),
    "profit_factor": ("profit_factor", "PF", "프로핏 팩터"),
    "total_return": ("total_return", "return", "average return", "총 수익률", "수익률"),
    "cagr": ("cagr", "CAGR"),
    "sharpe": ("sharpe", "Sharpe"),
    "win_rate": ("win_rate", "승률"),
    "average_trade": ("average_trade", "평균 거래 수익", "평균 거래 수익률"),
    "average_win": ("average_win", "평균 승리 수익"),
    "average_loss": ("average_loss", "평균 손실"),
    "expectancy": ("expectancy", "기대값"),
    "exposure": ("exposure", "노출"),
    "ending_equity": ("ending_equity", "최종 자산"),
}

_PERCENT_METRICS = {"total_return", "return", "cagr", "mdd", "max_drawdown", "win_rate", "exposure"}


def _authoritative_metric_tokens(output: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    for metrics in _authoritative_metric_dicts(output):
        for raw_key, raw_value in metrics.items():
            key = str(raw_key)
            aliases = _METRIC_ALIASES.get(key, (key,))
            values = _metric_value_strings(key, raw_value)
            for alias in aliases:
                for value in values:
                    tokens.add(f"{alias}={value}")
                    tokens.add(f"{alias} {value}")
                    if _looks_int(value):
                        tokens.add(f"{alias} {value}회")
    return tokens


def _authoritative_metric_dicts(output: dict[str, object]) -> tuple[dict[str, object], ...]:
    metrics: list[dict[str, object]] = []
    backtest = _as_dict(output.get("backtest"))
    backtest_metrics = _as_dict(backtest.get("metrics"))
    if backtest_metrics:
        metrics.append(backtest_metrics)
    for candidate in _as_list(output.get("candidates")):
        item = _as_dict(candidate)
        result = _as_dict(item.get("backtest_result"))
        candidate_metrics = _as_dict(result.get("metrics"))
        if candidate_metrics:
            metrics.append(candidate_metrics)
    comparison = _as_dict(output.get("comparison"))
    for row in _as_list(comparison.get("rows")):
        row_metrics = _as_dict(row)
        if row_metrics:
            metrics.append(row_metrics)
    validation = _as_dict(output.get("validation"))
    validation_metrics = _as_dict(validation.get("metrics"))
    if validation_metrics:
        metrics.append(validation_metrics)
    return tuple(metrics)


def _metric_value_strings(key: str, value: object) -> set[str]:
    values = {str(value)}
    try:
        numeric = float(str(value))
    except ValueError:
        return values
    if numeric.is_integer():
        values.add(str(int(numeric)))
    if key in _PERCENT_METRICS:
        percent = numeric * 100 if abs(numeric) <= 1 else numeric
        values.add(_trim_float(percent))
        values.add(f"{_trim_float(percent)}%")
    return values


def _trim_float(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _looks_int(value: str) -> bool:
    try:
        return float(value).is_integer()
    except ValueError:
        return False


def _reported_authoritative_alias_metrics(text: str) -> tuple[tuple[str, float], ...]:
    reported: list[tuple[str, float]] = []
    for metric_name, aliases in (
        ("trade_count", _METRIC_ALIASES["trade_count"]),
        ("wins", _METRIC_ALIASES["wins"]),
        ("losses", _METRIC_ALIASES["losses"]),
        ("mdd", _METRIC_ALIASES["mdd"]),
        ("profit_factor", _METRIC_ALIASES["profit_factor"]),
        ("total_return", _METRIC_ALIASES["total_return"]),
        ("cagr", _METRIC_ALIASES["cagr"]),
        ("sharpe", _METRIC_ALIASES["sharpe"]),
        ("win_rate", _METRIC_ALIASES["win_rate"]),
        ("average_trade", _METRIC_ALIASES["average_trade"]),
        ("average_win", _METRIC_ALIASES["average_win"]),
        ("average_loss", _METRIC_ALIASES["average_loss"]),
        ("expectancy", _METRIC_ALIASES["expectancy"]),
        ("exposure", _METRIC_ALIASES["exposure"]),
        ("ending_equity", _METRIC_ALIASES["ending_equity"]),
    ):
        for alias in aliases:
            if alias.isascii():
                prefix = rf"(?<![A-Za-z_]){re.escape(alias)}(?![A-Za-z_])"
            else:
                prefix = re.escape(alias)
            pattern = prefix + r"\s*(?:=|:)?\s*(-?\d+(?:\.\d+)?%?)"
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = _parse_metric_number(match.group(1), percent_metric=metric_name in _PERCENT_METRICS)
                if value is not None:
                    reported.append((metric_name, value))
    return tuple(reported)


def _authoritative_metric_numeric_values(output: dict[str, object], metric_name: str) -> set[float]:
    values: set[float] = set()
    keys = {metric_name}
    for key, aliases in _METRIC_ALIASES.items():
        if metric_name == key or metric_name in aliases:
            keys.add(key)
    for metrics in _authoritative_metric_dicts(output):
        for key in keys:
            value = _parse_metric_number(metrics.get(key), percent_metric=False)
            if value is not None:
                values.add(value)
                if key in _PERCENT_METRICS and abs(value) <= 1:
                    values.add(value * 100)
    return values


def _parse_metric_number(value: object, *, percent_metric: bool) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    is_percent = raw.endswith("%")
    if is_percent:
        raw = raw[:-1]
    try:
        number = float(raw)
    except ValueError:
        return None
    if is_percent and not percent_metric:
        return number
    return number


def _metric_numbers_match(reported: float, expected: float) -> bool:
    return abs(reported - expected) <= 0.000001


def _reported_trade_counts(text: str) -> tuple[int, ...]:
    patterns = (
        r"trade_count\s*=\s*(\d+)",
        r"거래\s*횟수\s*(\d+)\s*회",
        r"거래\s*(\d+)\s*회",
    )
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            values.append(int(match.group(1)))
    return tuple(values)


def _authoritative_trade_counts(output: dict[str, object]) -> set[int]:
    counts: set[int] = set()

    def add(value: object) -> None:
        if value is None:
            return
        try:
            counts.add(int(float(str(value))))
        except ValueError:
            return

    backtest = _as_dict(output.get("backtest"))
    add(_as_dict(backtest.get("metrics")).get("trade_count"))
    for candidate in _as_list(output.get("candidates")):
        item = _as_dict(candidate)
        result = _as_dict(item.get("backtest_result"))
        add(_as_dict(result.get("metrics")).get("trade_count"))
    comparison = _as_dict(output.get("comparison"))
    for row in _as_list(comparison.get("rows")):
        add(_as_dict(row).get("trade_count"))
    return counts


def _section_after(text: str, marker: str) -> str:
    index = text.find(marker)
    if index < 0:
        return ""
    tail = text[index + len(marker):]
    next_section = tail.find("[")
    return tail if next_section < 0 else tail[:next_section]


def _contains_performance_number(text: str) -> bool:
    metric_words = ("수익", "손실", "MDD", "trade_count", "win_rate", "profit", "return")
    return any(word in text for word in metric_words) and bool(re.search(r"\d+(?:\.\d+)?%?", text))


def _safe_critique(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    findings = []
    raw = value.get("findings")
    if isinstance(raw, list):
        for finding in raw[:5]:
            if isinstance(finding, dict):
                findings.append(
                    {
                        "severity": finding.get("severity", "unknown"),
                        "message": _ko(finding.get("message", "finding")),
                        "recommended_action": _ko(finding.get("recommended_action", "")),
                        "source": "fixture_qualitative_rule",
                    }
                )
    return {"decision": value.get("decision", "unknown"), "findings": findings}


def _safe_plan(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    actions = []
    raw = value.get("steps") or value.get("actions")
    if isinstance(raw, list):
        for item in raw[:5]:
            if isinstance(item, dict):
                actions.append({"description": _ko(item.get("description", "\uac80\uc99d \uc870\uac74\uc744 \ubcf4\uc644\ud569\ub2c8\ub2e4.")), "source": "fixture_qualitative_rule"})
            else:
                actions.append({"description": _ko(str(item)), "source": "fixture_qualitative_rule"})
    return {"actions": actions}


def _ko(value: object) -> str:
    text = str(value)
    return CRITIQUE_TRANSLATIONS.get(text) or ACTION_TRANSLATIONS.get(text) or text
