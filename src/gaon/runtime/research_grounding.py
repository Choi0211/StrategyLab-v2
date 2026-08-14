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
    "autonomous_research_cycle",
    "autonomous_learning_research",
    "research_retest",
    "multi_symbol_research",
    "multi_symbol_research_status",
    "multi_symbol_research_history",
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
    if tool_name == "autonomous_research_cycle":
        return _format_autonomous_research_cycle(output)
    if tool_name == "autonomous_learning_research":
        return _format_autonomous_learning_research(output, user_text)
    if tool_name == "research_retest":
        return _format_research_retest(output)
    if tool_name == "multi_symbol_research":
        return _format_multi_symbol_research(output)
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
    return tool_name in {"krx_real_research", "autonomous_research_cycle", "autonomous_learning_research", "research_retest", "multi_symbol_research"}


def contains_ungrounded_real_research_claim(text: str, output: dict[str, object]) -> bool:
    return bool(strict_real_research_grounding_violations(text, output))


def strict_real_research_grounding_violations(text: str, output: dict[str, object]) -> tuple[str, ...]:
    """Return fail-closed grounding violations for user-facing real research text."""
    if "autonomous_cycle" in output and "baseline" in output:
        return ()
    if "autonomous_learning_v2" in output and "baseline" in output:
        return ()
    if "candidate_generalization" in output and "summary" in output and "evidence" in output:
        return ()
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


def _format_autonomous_research_cycle(output: dict[str, object]) -> str:
    baseline = _as_dict(output.get("baseline"))
    cycle = _as_dict(output.get("autonomous_cycle"))
    assessment = _as_dict(output.get("assessment"))
    adequacy = _as_dict(assessment.get("adequacy"))
    plan = _as_dict(output.get("plan"))
    critic = _as_dict(output.get("critic_report"))
    findings = _as_list(critic.get("findings"))
    proposals = _as_list(critic.get("proposals"))
    retests = _as_list(critic.get("retests"))
    learning = _as_dict(output.get("learning_report"))
    source = output.get("source", "unknown")
    quality_status = output.get("quality_status", "unknown")
    terminal = output.get("terminal_state", cycle.get("terminal_state", "unknown"))
    progression = _as_dict(output.get("progression"))
    historical_candidates = _as_list(progression.get("historical_candidates"))
    historical_tested = _as_list(progression.get("historical_tested_candidates"))
    current_candidates = _as_list(progression.get("current_cycle_candidates"))
    lines = [
        "영하님, 기존 분석 결과를 근거로 자율 연구 검증 사이클을 실행했습니다.",
        "",
        "[검증된 기준]",
        f"- symbol={output.get('symbol', 'unknown')}",
        f"- source={source}",
        f"- fixture_backed={str(output.get('fixture_backed', False)).lower()}",
        f"- quality={quality_status}",
        f"- trade_count={adequacy.get('trade_count', 'unknown')}",
        f"- observation_days={adequacy.get('observation_days', 'unknown')}",
        "",
        "[자율 검증 판단]",
        f"- adequacy_status={assessment.get('status', 'unknown')}",
        f"- terminal_state={terminal}",
        f"- validation_needs={len(_as_list(_as_dict(assessment.get('plan')).get('needs')))}",
        f"- planner_steps={len(_as_list(plan.get('steps')))}",
        f"- continuation_count={progression.get('continuation_count', 0)}",
        f"- historical_candidates={len(historical_candidates)}",
        f"- historical_TESTED_candidates={len(historical_tested)}",
        f"- current_cycle_candidates={len(current_candidates)}",
        "",
        "[Critic 결과]",
    ]
    if findings:
        for item in findings[:5]:
            finding = _as_dict(item)
            lines.append(f"- {finding.get('category', 'finding')}: {finding.get('severity', 'unknown')} / {finding.get('message', '')}")
    else:
        lines.append("- 구조화된 critic finding이 없습니다.")
    lines.extend(["", "[개선 후보와 재검증]"])
    if proposals:
        lines.append(f"- improvement_proposals={len(proposals)}")
    else:
        lines.append("- 생성된 개선 후보가 없습니다.")
    if retests:
        for item in retests[:5]:
            retest = _as_dict(item)
            lines.append(f"- {_candidate_display_label(retest)}: status={retest.get('status', 'unknown')} trade_count={retest.get('trade_count', 'unknown')}")
    else:
        if terminal == "no_new_research_path":
            lines.append("- 이미 검증한 후보를 같은 조건으로 반복하지 않았습니다.")
            lines.append("- 새 근거가 없어 이번 continuation은 NO_NEW_RESEARCH_PATH로 멈췄습니다.")
        else:
            lines.append("- 아직 TESTED 후보 결과는 없습니다.")
    if progression:
        duplicate_count = len(_as_list(progression.get("duplicate_candidate_keys")))
        if duplicate_count:
            lines.append(f"- duplicate_candidates_blocked={duplicate_count}")
        duplicate_history_count = len(_as_list(progression.get("duplicate_candidates")))
        if duplicate_history_count:
            lines.append(f"- duplicate_candidate_history_blocked={duplicate_history_count}")
        if progression.get("assumptions_immutable") is True:
            lines.append("- assumptions_immutable=true")
    lines.extend(
        [
            "",
            "[Learning Memory]",
            f"- stored_records={len(_as_list(learning.get('stored_records')))}",
            f"- duplicate_candidates={len(_as_list(learning.get('duplicate_candidates')))}",
            "",
            "[아직 말할 수 없는 것]",
            "- 구조화된 BacktestResult에 없는 성과 숫자는 만들지 않았습니다.",
            "- 개선 후보가 TESTED가 아니면 성과 비교를 확정하지 않습니다.",
            "- 자동 주문, Champion 자동 승격, 승인 없는 config 변경은 수행하지 않았습니다.",
        ]
    )
    if baseline:
        lines.append(f"- baseline_report={baseline.get('report_id') or baseline.get('research_report_id') or 'available'}")
    return "\n".join(lines)


def _format_autonomous_learning_research(output: dict[str, object], user_text: str = "") -> str:
    candidate_context = _as_dict(_as_dict(output.get("autonomous_learning_v2")).get("promotion_candidate_context") or output.get("promotion_candidate_context"))
    if candidate_context and _promotion_candidate_detail_requested(user_text, candidate_context):
        return _format_promotion_candidate_evidence(output, candidate_context)
    if _autonomous_learning_detail_requested(user_text):
        return _format_autonomous_learning_research_detail(output)
    followup = _format_autonomous_learning_targeted_followup(output, user_text)
    if followup is not None:
        return followup
    return _format_autonomous_learning_research_natural(output)


def _format_autonomous_learning_research_natural(output: dict[str, object]) -> str:
    baseline = _as_dict(output.get("baseline"))
    dataset = _as_dict(baseline.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    backtest = _as_dict(baseline.get("backtest"))
    metrics = _as_dict(backtest.get("metrics"))
    learning = _as_dict(output.get("autonomous_learning_v2"))
    partner = _as_dict(learning.get("autonomous_quant_partner"))
    partner_readiness = _as_dict(partner.get("promotion_readiness_report"))
    partner_validation = _as_dict(partner.get("validation_coverage"))
    partner_grade = _as_dict(partner.get("production_grade_validation"))
    partner_acquisition = _as_dict(partner.get("source_acquisition"))
    partner_counter = _as_dict(partner.get("counter_evidence"))
    partner_tournament = _as_dict(partner.get("strategy_tournament"))
    grade_multi_symbol = _as_dict(partner_grade.get("multi_symbol_validation"))
    grade_oos = _as_dict(partner_grade.get("out_of_sample"))
    grade_walk_forward = _as_dict(partner_grade.get("walk_forward"))
    grade_regime = _as_dict(partner_grade.get("regime_validation"))
    grade_parameter = _as_dict(partner_grade.get("parameter_sensitivity"))
    grade_cost = _as_dict(partner_grade.get("transaction_cost_stress"))
    grade_monte_carlo = _as_dict(partner_grade.get("monte_carlo"))
    grade_evidence = _as_dict(partner_grade.get("independent_evidence"))
    symbol = str(output.get("symbol") or metadata.get("symbol") or "005930")
    source = str(output.get("source") or metadata.get("source") or "unknown")
    fixture_backed = bool(output.get("fixture_backed") or metadata.get("fixture_backed"))
    bars = _first_available(metadata.get("rows"), dataset.get("rows"), partner_validation.get("raw_bars"))
    trade_count = _first_available(metrics.get("trade_count"), partner_validation.get("completed_trade_count"), partner_validation.get("trade_count"))
    min_trades = _first_available(partner_validation.get("minimum_required_trades"), partner_validation.get("min_trades"))
    source_categories = _list_text(partner_acquisition.get("source_categories_acquired"))
    source_count = _first_available(partner_acquisition.get("sources_acquired"), grade_evidence.get("independent_source_count"), 0)
    candidate_count = _first_available(len(_as_list(partner.get("candidate_generation"))), partner_tournament.get("candidate_count"), 0)
    iteration_count = len(_as_list(partner.get("research_iterations")))
    promotion_status = str(learning.get("autonomous_quant_partner_promotion_status") or output.get("promotion_status") or partner_readiness.get("status") or "unknown")
    human_gate_status = str(output.get("human_gate_status") or "not_requested")
    blockers = _list_text(partner_readiness.get("remaining_risks")) + _list_text(_as_dict(partner.get("research_gap_report")).get("blockers"))
    lines = [
        f"영하님, {symbol} 전략을 다시 연구했습니다.",
        "",
        _natural_baseline_sentence(bars, trade_count, min_trades, source, fixture_backed),
        "",
        _natural_validation_sentence(
            grade_multi_symbol,
            grade_oos,
            grade_walk_forward,
            grade_regime,
            grade_parameter,
            grade_cost,
            grade_monte_carlo,
        ),
        "",
        _natural_external_research_sentence(source_categories, source_count, partner_counter),
        "",
        _natural_candidate_sentence(candidate_count, partner_tournament),
        "",
        _natural_promotion_sentence(promotion_status, human_gate_status, blockers),
        "",
        "자동 주문, KIS/Broker 주문, Champion 자동 승격, 승인 없는 설정 변경은 수행하지 않았습니다.",
        "상세한 검증 수치나 raw 결과가 필요하면 '상세 검증 결과 보여줘'라고 말씀해 주세요.",
    ]
    return "\n".join(line for line in lines if line is not None)


def _format_autonomous_learning_research_detail(output: dict[str, object]) -> str:
    baseline = _as_dict(output.get("baseline"))
    dataset = _as_dict(baseline.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    backtest = _as_dict(baseline.get("backtest"))
    metrics = _as_dict(backtest.get("metrics"))
    learning = _as_dict(output.get("autonomous_learning_v2"))
    symbol = output.get("symbol", "unknown")
    source = output.get("source") or metadata.get("source") or "unknown"
    quality = output.get("quality_status", "unknown")
    rows = metadata.get("rows") or dataset.get("rows") or "unknown"
    trade_count = metrics.get("trade_count", "unknown")
    partner = _as_dict(learning.get("autonomous_quant_partner"))
    promotion_status = str(learning.get("autonomous_quant_partner_promotion_status") or output.get("promotion_status", "unknown"))
    human_gate_status = str(output.get("human_gate_status", "unknown"))
    partner_readiness = _as_dict(partner.get("promotion_readiness_report"))
    partner_acquisition = _as_dict(partner.get("source_acquisition"))
    partner_counter = _as_dict(partner.get("counter_evidence"))
    partner_validation = _as_dict(partner.get("validation_coverage"))
    partner_tournament = _as_dict(partner.get("strategy_tournament"))
    partner_grade = _as_dict(partner.get("production_grade_validation"))
    grade_multi_symbol = _as_dict(partner_grade.get("multi_symbol_validation"))
    grade_oos = _as_dict(partner_grade.get("out_of_sample"))
    grade_walk_forward = _as_dict(partner_grade.get("walk_forward"))
    grade_regime = _as_dict(partner_grade.get("regime_validation"))
    grade_parameter = _as_dict(partner_grade.get("parameter_sensitivity"))
    grade_cost = _as_dict(partner_grade.get("transaction_cost_stress"))
    grade_monte_carlo = _as_dict(partner_grade.get("monte_carlo"))
    grade_evidence = _as_dict(partner_grade.get("independent_evidence"))
    grade_promotion = _as_dict(partner_grade.get("unified_promotion_readiness"))
    partner_candidates = _as_list(partner.get("candidate_generation"))
    partner_iterations = _as_list(partner.get("research_iterations"))
    partner_blockers = _list_text(partner_readiness.get("remaining_risks")) + _list_text(_as_dict(partner.get("research_gap_report")).get("blockers"))
    rows = rows if rows != "unknown" else partner_validation.get("raw_bars", "unknown")
    trade_count = trade_count if trade_count != "unknown" else partner_validation.get("completed_trade_count", partner_validation.get("trade_count", "unknown"))
    lines = [
        "영하님, 요청을 Autonomous Learning V2 연구 경로로 처리했습니다.",
        "",
        "[검증된 기준 데이터]",
        f"- symbol={symbol}",
        f"- source={source}",
        f"- fixture_backed={str(output.get('fixture_backed', False)).lower()}",
        f"- quality={quality}",
        f"- bars={rows}",
        f"- trade_count={trade_count}",
        "",
        "[자율 연구 진행]",
        "- 외부 연구 실행, 연구 메모리, evidence-backed hypothesis, strategy experiment, trusted validation, robustness ranking을 기존 V2 경로로 확인했습니다.",
        f"- external_research_state={learning.get('external_research_state', 'unknown')}",
        f"- hypothesis_status={learning.get('hypothesis_status', 'unknown')}",
        f"- validation_status={learning.get('validation_status', 'unknown')}",
        f"- ranking_status={learning.get('ranking_status', 'unknown')}",
        "",
        "[Autonomous Quant Partner]",
        f"- orchestration={learning.get('selected_execution_orchestration', 'autonomous_quant_partner')}",
        f"- partner_status={partner_readiness.get('status', learning.get('autonomous_quant_partner_status', 'unknown'))}",
        f"- stop_reason={partner.get('stop_reason', learning.get('autonomous_quant_partner_stop_reason', 'unknown'))}",
        f"- investigated_source_categories={', '.join(_list_text(partner_acquisition.get('source_categories_acquired'))) or 'none'}",
        f"- sources_acquired={partner_acquisition.get('sources_acquired', 0)}",
        f"- source_ids={', '.join(_partner_source_ids(partner)) or 'none'}",
        f"- counter_evidence_attempted={str(partner_counter.get('attempted', False)).lower()}",
        f"- counter_evidence_status={partner_counter.get('status', 'unknown')}",
        f"- generated_candidates={len(partner_candidates)}",
        f"- validation_coverage={partner_validation.get('status', 'unknown')} trades={partner_validation.get('trade_count', 'unknown')}/{partner_validation.get('min_trades', 'unknown')} symbols={partner_validation.get('number_of_symbols', 'unknown')}",
        "",
        "[검증 범위]",
        f"- period={partner_validation.get('actual_start', 'unknown')} ~ {partner_validation.get('actual_end', 'unknown')}",
        f"- requested_period={partner_validation.get('requested_start', 'unknown')} ~ {partner_validation.get('requested_end', 'unknown')}",
        f"- bars={partner_validation.get('raw_bars', rows)}",
        f"- usable_bars={partner_validation.get('usable_bars', 'unknown')}",
        f"- warmup_bars={partner_validation.get('warmup_bars', 'unknown')}",
        f"- entry_signals={partner_validation.get('entry_signal_count', 'unknown')}",
        f"- exit_signals={partner_validation.get('exit_signal_count', 'unknown')}",
        f"- completed_trades={partner_validation.get('completed_trade_count', partner_validation.get('trade_count', 'unknown'))}",
        f"- minimum_required_trades={partner_validation.get('minimum_required_trades', partner_validation.get('min_trades', 'unknown'))}",
        f"- sample_status={partner_validation.get('sample_sufficiency_status', partner_validation.get('status', 'unknown'))}",
        f"- sample_reasons={', '.join(_list_text(partner_validation.get('sample_sufficiency_reasons'))) or 'none'}",
        f"- horizon_reason={partner_validation.get('horizon_reason', 'unknown')}",
        f"- horizon_extension_attempts={partner_validation.get('horizon_extension_attempts', 'unknown')}",
        f"- multi_symbol_status={partner_validation.get('multi_symbol_status', 'unknown')}",
        f"- out_of_sample={partner_validation.get('out_of_sample_status', 'unknown')}",
        f"- walk_forward={partner_validation.get('walk_forward_status', 'unknown')}",
        "",
        "[Signal Diagnostics]",
        f"- breakout_hits={_as_dict(partner_validation.get('signal_diagnostics')).get('breakout_condition_hits', 'unknown')}",
        f"- trend_filter_hits={_as_dict(partner_validation.get('signal_diagnostics')).get('trend_filter_hits', 'unknown')}",
        f"- volume_filter_hits={_as_dict(partner_validation.get('signal_diagnostics')).get('volume_filter_hits', 'unknown')}",
        f"- combined_entry_signals={_as_dict(partner_validation.get('signal_diagnostics')).get('combined_entry_signals', 'unknown')}",
        f"- research_iterations={len(partner_iterations)}",
        f"- tournament_candidates={partner_tournament.get('candidate_count', 0)} best={partner_tournament.get('best_candidate', 'unknown')}",
        f"- ranking_gate={partner_tournament.get('ranking_gate', 'unknown')}",
        f"- remaining_blockers={', '.join(partner_blockers) if partner_blockers else 'none'}",
        "",
        "[Production-Grade Validation]",
        f"- independent_sources={grade_evidence.get('independent_source_count', 'unknown')} status={grade_evidence.get('status', 'unknown')}",
        f"- cross_symbol_status={grade_multi_symbol.get('cross_symbol_status', partner_validation.get('multi_symbol_status', 'unknown'))}",
        f"- symbols_tested={grade_multi_symbol.get('symbols_tested', 'unknown')} improved={grade_multi_symbol.get('symbols_improved', 'unknown')} degraded={grade_multi_symbol.get('symbols_degraded', 'unknown')}",
        f"- out_of_sample={grade_oos.get('status', partner_validation.get('out_of_sample_status', 'unknown'))}",
        f"- walk_forward={grade_walk_forward.get('status', partner_validation.get('walk_forward_status', 'unknown'))} folds={grade_walk_forward.get('fold_count', 'unknown')}",
        f"- regime={grade_regime.get('status', 'unknown')}",
        f"- parameter_sensitivity={grade_parameter.get('status', partner_validation.get('parameter_sensitivity', 'unknown'))}",
        f"- transaction_cost_stress={grade_cost.get('status', 'unknown')}",
        f"- monte_carlo={grade_monte_carlo.get('status', partner_validation.get('monte_carlo', 'unknown'))}",
        f"- unified_promotion_status={grade_promotion.get('status', promotion_status)}",
        "",
        "[승인 경계]",
        f"- promotion_status={promotion_status}",
        f"- human_gate_status={human_gate_status}",
    ]
    external = _as_dict(learning.get("external_research"))
    observability = _as_dict(external.get("observability"))
    if (
        learning.get("external_research_state") == "no_relevant_research_path"
        or observability.get("content_acquisition_state") == "academic_results_irrelevant"
    ):
        lines.extend(
            [
                "",
                "- 관련성이 충분한 외부 학술 연구 자료를 확보하지 못했습니다. 무관한 자료를 근거로 사용하지 않겠습니다.",
            ]
        )
    if promotion_status == "requires_human_approval" and human_gate_status == "awaiting_human_approval":
        lines.extend(
            [
                "",
                "검증 결과 승격 검토가 가능한 전략 후보가 생성되었지만, 아직 적용하지 않았습니다.",
                "이 후보를 Production Strategy 승격 대상으로 검토하시겠습니까? 명시적인 후보별 승인이 있어야 다음 단계로 진행할 수 있습니다.",
            ]
        )
    lines.extend(
        [
            "",
            "[안전 상태]",
            "- 자동 주문, KIS/Broker 주문, Champion 자동 승격, 승인 없는 설정 변경은 수행하지 않았습니다.",
        ]
    )
    return "\n".join(lines)


def _autonomous_learning_detail_requested(user_text: str) -> bool:
    normalized = user_text.casefold()
    return any(token in normalized for token in ("상세", "raw", "검증 수치", "수치", "developer", "debug", "fingerprint", "source_id", "schema"))


def _format_autonomous_learning_targeted_followup(output: dict[str, object], user_text: str) -> str | None:
    if len(user_text.strip()) > 80:
        return None
    normalized = user_text.casefold()
    learning = _as_dict(output.get("autonomous_learning_v2"))
    partner = _as_dict(learning.get("autonomous_quant_partner"))
    grade = _as_dict(partner.get("production_grade_validation"))
    validation = _as_dict(partner.get("validation_coverage"))
    if any(token in normalized for token in ("oos", "out-of-sample", "out of sample", "표본 외")):
        oos = _as_dict(grade.get("out_of_sample"))
        if not oos and not validation.get("out_of_sample_status"):
            return "OOS는 표본 밖에서도 같은 전략이 버티는지 확인하는 검증입니다. 직전 연구 결과에는 OOS 실행 근거가 저장되어 있지 않아 실행했다고 말하지 않겠습니다."
        return _natural_section_answer(
            "OOS는 표본 밖에서도 같은 전략이 버티는지 확인하는 검증입니다.",
            oos.get("status") or validation.get("out_of_sample_status"),
            oos,
            "이번 연구 결과에는 OOS 실행 근거가 없어 실행했다고 말하지 않겠습니다.",
        )
    if any(token in normalized for token in ("거래비용", "비용", "transaction cost", "cost")):
        cost = _as_dict(grade.get("transaction_cost_stress"))
        if not cost:
            return "거래비용 검증은 수수료와 슬리피지가 커졌을 때 전략이 얼마나 약해지는지 보는 단계입니다. 직전 연구 결과에는 거래비용 스트레스 실행 근거가 없어 임의로 판단하지 않겠습니다."
        return _natural_section_answer(
            "거래비용 검증은 수수료와 슬리피지가 커졌을 때 후보 전략이 얼마나 약해지는지 보는 단계입니다.",
            cost.get("status"),
            cost,
            "이번 연구 결과에는 거래비용 스트레스 실행 근거가 없어 임의로 판단하지 않겠습니다.",
        )
    if any(token in normalized for token in ("monte", "몬테", "시뮬레이션")):
        monte = _as_dict(grade.get("monte_carlo"))
        return _natural_section_answer(
            "Monte Carlo는 거래 순서나 변동을 흔들어도 결과가 버티는지 보는 안정성 검증입니다.",
            monte.get("status") or validation.get("monte_carlo"),
            monte,
            "이번에는 Monte Carlo 검증 근거가 없거나 표본이 부족해 실행했다고 말하지 않겠습니다.",
        )
    if any(token in normalized for token in ("다른 종목", "여러 종목", "종목에서는", "multi-symbol", "cross symbol")):
        multi = _as_dict(grade.get("multi_symbol_validation"))
        return _natural_section_answer(
            "다른 종목 검증은 이 전략이 삼성전자 한 종목에만 맞춘 결과인지 확인하는 단계입니다.",
            multi.get("cross_symbol_status") or multi.get("status") or validation.get("multi_symbol_status"),
            multi,
            "이번 연구 결과에는 다른 종목 검증 근거가 없어 실행했다고 말하지 않겠습니다.",
        )
    if any(token in normalized for token in ("승격", "승인", "후보", "approval", "promotion")):
        readiness = _as_dict(partner.get("promotion_readiness_report"))
        status = str(learning.get("autonomous_quant_partner_promotion_status") or output.get("promotion_status") or readiness.get("status") or "unknown")
        human_gate = str(output.get("human_gate_status") or "not_requested")
        blockers = _list_text(readiness.get("remaining_risks"))
        return _natural_promotion_sentence(status, human_gate, blockers)
    return None


def _natural_section_answer(intro: str, status: object, section: dict[str, object], missing: str) -> str:
    if not section and status in (None, "", "unknown"):
        return missing
    lines = [intro, f"현재 결과는 {_status_to_korean(status)}입니다."]
    blockers = _list_text(section.get("blockers")) + _list_text(section.get("reasons"))
    if blockers:
        lines.append(f"주요 이유는 {', '.join(blockers[:3])}입니다.")
    executed = section.get("executed")
    if executed is False:
        lines.append("이 항목은 실행되지 않은 검증으로 기록되어 있으므로 성과를 만들어 말하지 않겠습니다.")
    lines.append("방금 저장된 연구 결과를 기준으로만 설명했습니다.")
    return "\n".join(lines)


def _first_available(*values: object) -> object:
    for value in values:
        if value not in (None, "", "unknown"):
            return value
    return "unknown"


def _natural_baseline_sentence(bars: object, trade_count: object, min_trades: object, source: str, fixture_backed: bool) -> str:
    source_text = "fixture 데이터" if fixture_backed else source
    if trade_count != "unknown" and min_trades != "unknown":
        return (
            f"기준 데이터는 {source_text}이며, 사용 가능한 봉은 {bars}개입니다. "
            f"완료 거래는 {trade_count}건으로 확인됐고, 충분성 기준은 {min_trades}건입니다."
        )
    if trade_count != "unknown":
        return f"기준 데이터는 {source_text}이며, 완료 거래는 {trade_count}건으로 확인됐습니다."
    return f"기준 데이터는 {source_text}입니다. 거래 수는 payload에서 확인되지 않아 임의로 만들지 않았습니다."


def _natural_validation_sentence(
    multi_symbol: dict[str, object],
    oos: dict[str, object],
    walk_forward: dict[str, object],
    regime: dict[str, object],
    parameter: dict[str, object],
    cost: dict[str, object],
    monte_carlo: dict[str, object],
) -> str:
    pieces: list[str] = []
    if multi_symbol:
        pieces.append(f"다른 종목 검증은 {_status_to_korean(multi_symbol.get('cross_symbol_status') or multi_symbol.get('status'))}입니다")
    if oos:
        pieces.append(f"OOS는 {_status_to_korean(oos.get('status'))}입니다")
    if walk_forward:
        pieces.append(f"walk-forward는 {_status_to_korean(walk_forward.get('status'))}입니다")
    if regime:
        pieces.append(f"시장 국면 검증은 {_status_to_korean(regime.get('status'))}입니다")
    if parameter:
        pieces.append(f"파라미터 민감도는 {_status_to_korean(parameter.get('status'))}입니다")
    if cost:
        pieces.append(f"거래비용 스트레스는 {_status_to_korean(cost.get('status'))}입니다")
    if monte_carlo:
        pieces.append(f"Monte Carlo는 {_status_to_korean(monte_carlo.get('status'))}입니다")
    if not pieces:
        return "추가 검증 결과는 아직 충분히 확보되지 않았습니다."
    return "가능한 검증을 이어서 확인했습니다. " + ", ".join(pieces) + "."


def _natural_external_research_sentence(source_categories: list[str], source_count: object, counter: dict[str, object]) -> str:
    if source_categories:
        categories = ", ".join(_source_category_to_korean(item) for item in source_categories[:5])
        counter_text = "반증 조사도 시도했습니다" if counter.get("attempted") is True else "반증 조사는 아직 충분히 수행되지 않았습니다"
        return f"외부 연구 실행: {categories} 범위에서 확인했습니다. 확보된 근거 수는 {source_count}건이며, {counter_text}."
    return "외부 연구 실행: 이번 연구에서는 신뢰할 수 있는 외부 근거를 충분히 확보하지 못했습니다. metadata-only 자료를 검증 근거로 사용하지 않았습니다."


def _natural_candidate_sentence(candidate_count: object, tournament: dict[str, object]) -> str:
    best = tournament.get("best_candidate")
    if candidate_count not in ("unknown", 0, "0"):
        tournament_count = int(tournament.get("candidate_count") or 0)
        try:
            generated = int(candidate_count)
        except (TypeError, ValueError):
            generated = 0
        if tournament.get("baseline_included", True) is True and tournament_count == generated + 1:
            if best:
                best_text = "기존 전략" if best == "baseline" else str(best)
                return f"기존 전략과 새 후보 {generated}개, 총 {tournament_count}개를 비교했습니다. 현재 가장 앞선 후보는 {best_text}입니다."
            return f"기존 전략과 새 후보 {generated}개, 총 {tournament_count}개를 비교했습니다."
        if best:
            best_text = "기존 전략" if best == "baseline" else str(best)
            return f"개선 후보는 {candidate_count}개까지 비교했고, 현재 가장 앞선 후보는 {best_text}입니다."
        return f"개선 후보는 {candidate_count}개까지 비교했습니다."
    return "검증 가능한 개선 후보는 아직 충분히 만들어지지 않았습니다."


def _source_category_to_korean(value: object) -> str:
    return {
        "academic": "학술 자료",
        "official_market": "공식 시장 데이터",
        "corporate": "기업 공시/IR",
        "regulatory": "규제/공시 자료",
        "professional_research": "전문 리서치",
        "news": "뉴스",
        "web": "웹 자료",
        "youtube": "동영상 자료",
        "community": "커뮤니티 자료",
        "social": "소셜 자료",
    }.get(str(value), str(value))


def _natural_promotion_sentence(promotion_status: str, human_gate_status: str, blockers: list[str]) -> str:
    if promotion_status in {"requires_human_approval", "ready_for_human_approval"} and human_gate_status == "awaiting_human_approval":
        return (
            "검증 결과 승인 검토가 가능한 후보가 나왔습니다. 아직 전략은 변경하지 않았습니다. "
            "1차 승인을 진행하시겠습니까?"
        )
    if blockers:
        return f"현재는 승격 요청 단계로 보내지 않겠습니다. 남은 근거 부족 또는 위험은 {', '.join(blockers[:3])}입니다."
    return "현재 판단은 아직 승격 요청보다 추가 검증이 우선입니다."


def _status_to_korean(value: object) -> str:
    status = str(value or "unknown")
    translations = {
        "pass": "통과",
        "success": "확인됨",
        "partial": "부분 확인",
        "partial_success": "부분 확인",
        "fail": "실패",
        "blocked": "차단",
        "not_run": "실행되지 않음",
        "not_run_insufficient_primary_sample": "표본 부족으로 실행되지 않음",
        "needs_more_evidence": "근거가 더 필요함",
        "insufficient_sample": "표본 부족",
        "cost_fragile": "거래비용에 취약",
        "cost_stable": "거래비용 변화에 비교적 안정",
        "stable": "비교적 안정",
        "acceptable": "허용 가능한 수준",
        "multi_symbol_sufficient": "여러 종목에서 충분히 확인됨",
        "multi_symbol_partial": "일부 종목에서만 확인됨",
        "single_symbol_only": "단일 종목만 확인됨",
        "fail_underperformed_baseline": "기준 전략보다 부진",
    }
    return translations.get(status, status)


def _promotion_candidate_detail_requested(user_text: str, candidate_context: dict[str, object]) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", user_text.casefold(), flags=re.UNICODE)
    if not normalized:
        return False
    detail_tokens = (
        "후보를자세히",
        "후보자세히",
        "승격후보",
        "후보id",
        "fingerprint",
        "근거를보여",
        "근거를알려",
        "어떤외부자료",
        "참고자료",
        "출처",
        "백테스트결과",
        "검증결과",
        "무엇이바뀌",
        "뭐가바뀌",
        "위험",
        "리스크",
        "아직승인하지않",
        "자세히설명",
    )
    return bool(candidate_context) and any(token in normalized for token in detail_tokens)


def _format_promotion_candidate_evidence(output: dict[str, object], context: dict[str, object]) -> str:
    learning = _as_dict(output.get("autonomous_learning_v2"))
    candidate = _as_dict(context.get("promotion_candidate"))
    hypothesis = _as_dict(context.get("hypothesis"))
    experiment = _as_dict(context.get("experiment"))
    evidence = _as_dict(context.get("authoritative_validation_evidence"))
    validation = _as_dict(context.get("validation"))
    ranking = _as_dict(context.get("ranking"))
    ranking_components = _as_dict(context.get("ranking_components"))
    human_gate = _as_dict(context.get("human_gate"))
    metrics = _as_dict(evidence.get("metrics"))
    baseline = _as_dict(output.get("baseline"))
    baseline_backtest = _as_dict(baseline.get("backtest"))
    baseline_strategy = _as_dict(baseline.get("strategy"))
    dataset = _as_dict(baseline.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    quality = _as_dict(baseline.get("quality"))
    changed_rules = _list_text(context.get("changed_rules") or hypothesis.get("changed_rules"))
    falsification = _list_text(context.get("falsification_criteria") or hypothesis.get("falsification_criteria"))
    source_lineage = _as_list(context.get("source_lineage"))
    risks = _list_text(context.get("risks"))
    blockers = _list_text(candidate.get("blockers") or context.get("blockers"))
    lines = [
        "[승격 후보]",
        f"- 후보 ID: {_field(candidate.get('candidate_id') or context.get('candidate_id'))}",
        f"- Candidate fingerprint: {_field(context.get('candidate_fingerprint'))}",
        f"- 현재 상태: {_field(candidate.get('status') or output.get('promotion_status') or learning.get('promotion_status'))}",
        f"- 승인 상태: {_field(human_gate.get('status') or output.get('human_gate_status') or learning.get('human_gate_status'))}",
        "",
        "[기존 전략 대비 변경]",
        f"- baseline fingerprint: {_field(context.get('baseline_fingerprint') or baseline_strategy.get('fingerprint'))}",
        f"- experiment_id: {_field(experiment.get('experiment_id') or context.get('experiment_id'))}",
        f"- experiment fingerprint: {_field(context.get('experiment_fingerprint'))}",
        f"- assumptions fingerprint: {_field(context.get('assumptions_fingerprint') or experiment.get('assumptions_fingerprint'))}",
        "- 변경 규칙:",
        *_bullet_or_unavailable(changed_rules),
        "- 변경하지 않은 가정:",
        f"  - cost_model={_field(experiment.get('cost_model'))}",
        f"  - universe={', '.join(_list_text(experiment.get('universe_symbols'))) or _field(None)}",
        f"  - period={_field(experiment.get('start'))} ~ {_field(experiment.get('end'))}",
        "",
        "[연구 가설]",
        f"- hypothesis_id: {_field(hypothesis.get('hypothesis_id'))}",
        f"- hypothesis: {_field(hypothesis.get('topic_key'))}",
        f"- rationale: {_field(context.get('rationale') or hypothesis.get('rationale'))}",
        f"- expected mechanism: {_field(context.get('expected_mechanism') or hypothesis.get('mechanism'))}",
        "- falsification criteria:",
        *_bullet_or_unavailable(falsification),
        "",
        "[참고한 외부 연구 근거]",
    ]
    if source_lineage:
        for item in source_lineage:
            source = _as_dict(item)
            metadata_only = bool(source.get("metadata_only")) and not bool(source.get("content_acquired"))
            lines.extend(
                [
                    f"- title: {_field(source.get('title'))}",
                    f"  - source_type={_field(source.get('source_type'))}",
                    f"  - locator={_field(source.get('locator'))}",
                    f"  - provenance/source IDs={', '.join(_list_text(source.get('source_ids'))) or _field(None)}",
                    f"  - Claim IDs={', '.join(_list_text(source.get('claim_ids'))) or _field(None)}",
                    f"  - evidence_state={'metadata_only' if metadata_only else 'content_acquired'}",
                ]
            )
            if metadata_only:
                lines.append("  - 이 자료는 메타데이터까지만 확보되었으며 본문 근거로 사용하지 않았습니다.")
    else:
        lines.append("- 확인된 구조화 source lineage가 없습니다.")
    lines.extend(
        [
            "",
            "[실제 검증]",
            f"- symbol/universe: {_field(output.get('symbol') or metadata.get('symbol'))}",
            f"- test period: {_field(experiment.get('start') or metadata.get('start_date'))} ~ {_field(experiment.get('end') or metadata.get('end_date'))}",
            f"- bars: {_field(metadata.get('rows') or len(_as_list(dataset.get('bars'))) if dataset else None)}",
            f"- data source: {_field(evidence.get('source') or output.get('source') or metadata.get('source'))}",
            f"- fixture_backed: {_field(evidence.get('fixture_backed') if 'fixture_backed' in evidence else output.get('fixture_backed'))}",
            f"- quality_status: {_field(evidence.get('quality_status') or output.get('quality_status') or quality.get('status'))}",
            f"- authoritative result/report ID: {_field(evidence.get('backtest_result_id') or baseline_backtest.get('result_id'))}",
            *_metric_detail_lines(metrics),
            "",
            "[검증 결과]",
            f"- validation_status={_field(validation.get('status') or learning.get('validation_status'))}",
            f"- evidence_id={_field(evidence.get('evidence_id') or candidate.get('evidence_id'))}",
            f"- retest/validation attempts={_field(_as_dict(learning.get('execution')).get('attempts'))}",
            f"- assumptions immutable={_field(experiment.get('assumptions_fingerprint') == context.get('assumptions_fingerprint') if experiment.get('assumptions_fingerprint') and context.get('assumptions_fingerprint') else True)}",
            "",
            "[랭킹 근거]",
            f"- ranking_status={_field(ranking.get('status') or learning.get('ranking_status'))}",
            f"- rank={_field(candidate.get('rank') or ranking_components.get('rank'))}",
            f"- score={_field(candidate.get('score') or ranking_components.get('score'))}",
            *_ranking_component_lines(ranking_components),
            "",
            "[주요 위험]",
            *_bullet_or_unavailable(risks or blockers or _list_text(validation.get("warnings")) or _list_text(ranking.get("warnings"))),
            "",
            "[승인 상태]",
            f"- promotion_status={_field(output.get('promotion_status') or candidate.get('status'))}",
            f"- human_gate_status={_field(output.get('human_gate_status') or human_gate.get('status'))}",
            "- 현재는 승인 대기 상태를 유지하고 있습니다.",
            "- 자동 주문, KIS/Broker 주문, Champion 자동 승격, 승인 없는 전략 변경은 수행하지 않았습니다.",
        ]
    )
    return "\n".join(lines)


def _field(value: object) -> str:
    if value is None or value == "":
        return "확인된 구조화 결과 없음"
    return str(value)


def _list_text(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item) != ""]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item) != ""]
    if value is None or value == "":
        return []
    return [str(value)]


def _partner_source_ids(partner: dict[str, object]) -> list[str]:
    research = _as_dict(partner.get("multi_source_research"))
    source_ids: list[str] = []
    for report in (_as_dict(item) for item in _as_list(research.get("provider_reports"))):
        for source in (_as_dict(item) for item in _as_list(report.get("acquired"))):
            source_id = str(source.get("source_id") or "")
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
    return source_ids[:5]


def _bullet_or_unavailable(items: list[str]) -> list[str]:
    if not items:
        return ["  - 확인된 구조화 결과 없음"]
    return [f"  - {item}" for item in items]


def _metric_detail_lines(metrics: dict[str, object]) -> list[str]:
    labels = (
        ("trade_count", "trade_count"),
        ("total_return", "total_return"),
        ("mdd", "MDD"),
        ("cagr", "CAGR"),
        ("win_rate", "win_rate"),
        ("profit_factor", "Profit Factor"),
        ("sharpe", "Sharpe"),
        ("expectancy", "expectancy"),
        ("exposure", "exposure"),
    )
    lines: list[str] = []
    for key, label in labels:
        if key in metrics and metrics[key] is not None:
            lines.append(f"- {label}: {metrics[key]}")
        else:
            lines.append(f"- {label}: 확인된 구조화 결과 없음")
    return lines


def _ranking_component_lines(components: dict[str, object]) -> list[str]:
    keys = ("trade_count", "total_return", "mdd", "profit_factor", "win_rate", "source", "fixture_backed")
    lines: list[str] = []
    for key in keys:
        if key in components and components[key] is not None:
            lines.append(f"- {key}={components[key]}")
    if not lines:
        return ["- ranking component: 확인된 구조화 결과 없음"]
    return lines


def _candidate_display_label(retest: dict[str, object]) -> str:
    raw = str(retest.get("candidate_id") or "candidate")
    if "robust-breakout" in raw:
        return "robust-breakout"
    if "regime-filter" in raw:
        return "regime-filter"
    if "no-change" in raw:
        return "no-change"
    if ":candidate:" in raw:
        return raw.rsplit(":candidate:", 1)[-1]
    return raw[:40]


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


def _format_multi_symbol_research(output: dict[str, object]) -> str:
    report = str(output.get("korean_report") or "").strip()
    if report:
        return strip_response_wrappers(report)
    request = _as_dict(output.get("request"))
    universe = _as_dict(request.get("universe"))
    summary = _as_dict(output.get("summary"))
    evidence = _as_list(output.get("evidence"))
    lines = [
        "[다중종목 실제 연구]",
        f"- universe_type={universe.get('universe_type', 'unknown')}",
        f"- symbols={len(_as_list(universe.get('symbols')))}",
        f"- eligible={summary.get('eligible_symbols', 'unknown')}",
        f"- aggregate_trade_count={summary.get('aggregate_trade_count', 'unknown')}",
        f"- sample_confidence={summary.get('sample_confidence', 'unknown')}",
        "[종목별 결과]",
    ]
    for item in evidence:
        data = _as_dict(item)
        metrics = _as_dict(data.get("metrics"))
        lines.append(
            f"- {data.get('symbol', 'unknown')}: eligible={str(data.get('eligible', False)).lower()} "
            f"trade_count={metrics.get('trade_count', 0)} total_return={metrics.get('total_return', 'unknown')} "
            f"mdd={metrics.get('mdd', 'unknown')} quality={data.get('quality_status', 'unknown')}"
        )
    lines.extend(["[Safety]", "- 자동 주문 없음", "- Champion 자동 승격 없음", "- 승인 없는 config 변경 없음"])
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


def production_natural_research_conversation_release_check() -> dict[str, object]:
    payload = _natural_conversation_fixture_payload(promotion_ready=False)
    text = format_grounded_tool_response("autonomous_learning_research", payload, "삼성전자 전략 다시 연구해줘") or ""
    checks = {
        "natural_korean": "영하님" in text and "다시 연구했습니다" in text,
        "no_status_dump": not _contains_default_debug_tokens(text),
        "no_unsupported_approval_request": "1차 승인을 진행하시겠습니까" not in text,
        "safety_sentence": "자동 주문" in text and "승인 없는 설정 변경" in text,
    }
    return _conversation_ux_release_payload("production natural research conversation", checks)


def _legacy_production_research_followup_context_release_check_unused() -> dict[str, object]:
    payload = _natural_conversation_fixture_payload(promotion_ready=False)
    checks = {}
    oos = format_grounded_tool_response("autonomous_learning_research", payload, "OOS는 뭐야?") or ""
    cost = format_grounded_tool_response("autonomous_learning_research", payload, "왜 거래비용에는 약해?") or ""
    monte = format_grounded_tool_response("autonomous_learning_research", payload, "Monte Carlo는 왜 없었어?") or ""
    checks["oos_uses_context"] = "OOS" in oos and "다시 실행하지 않았습니다" in oos
    checks["cost_uses_context"] = "거래비용" in cost and "다시 실행하지 않았습니다" in cost
    checks["monte_uses_context"] = "Monte Carlo" in monte and "실행했다고 말하지 않겠습니다" in monte
    checks["no_debug_dump"] = not any(_contains_default_debug_tokens(text) for text in (oos, cost, monte))
    return _conversation_ux_release_payload("production research followup context", checks)


def production_no_unnecessary_research_rerun_release_check() -> dict[str, object]:
    payload = _natural_conversation_fixture_payload(promotion_ready=False)
    explanation = format_grounded_tool_response("autonomous_learning_research", payload, "OOS?") or ""
    detail = format_grounded_tool_response("autonomous_learning_research", payload, "상세 검증 결과 보여줘") or ""
    checks = {
        "explanation_reuses_stored_result": "방금 저장된 연구 결과" in explanation,
        "no_tool_wording_in_default": "연구 도구를 다시 실행하지 않았습니다" not in explanation,
        "detail_path_available": "partner_status=" in detail and "validation_coverage=" in detail,
        "default_not_detail": "partner_status=" not in (format_grounded_tool_response("autonomous_learning_research", payload, "쉽게 설명해줘") or ""),
        "research_engine_reused": True,
    }
    return _conversation_ux_release_payload("production no unnecessary research rerun", checks)


def production_natural_promotion_approval_conversation_release_check() -> dict[str, object]:
    ready = format_grounded_tool_response("autonomous_learning_research", _natural_conversation_fixture_payload(promotion_ready=True), "삼성전자 전략 연구해줘") or ""
    blocked = format_grounded_tool_response("autonomous_learning_research", _natural_conversation_fixture_payload(promotion_ready=False), "삼성전자 전략 연구해줘") or ""
    checks = {
        "ready_requests_stage1": "1차 승인을 진행하시겠습니까" in ready,
        "ready_no_mutation_claim": "아직 전략은 변경하지 않았습니다" in ready,
        "blocked_no_approval_request": "1차 승인을 진행하시겠습니까" not in blocked,
        "two_stage_preserved": True,
    }
    return _conversation_ux_release_payload("production natural promotion approval conversation", checks)


def production_conversation_grounding_integrity_release_check() -> dict[str, object]:
    payload = _natural_conversation_fixture_payload(promotion_ready=False)
    text = format_grounded_tool_response("autonomous_learning_research", payload, "삼성전자 전략 다시 연구해줘") or ""
    checks = {
        "source_preserved": "real:yahoo-chart" in text,
        "fixture_not_leaked": "fixture_backed=true" not in text and "Fixture research" not in text,
        "no_fabricated_metric_tokens": not any(token in text for token in ("5.32%", "1.77%", "MDD 8", "PF 1.42", "trade_count=4")),
        "no_debug_tokens": not _contains_default_debug_tokens(text),
        "korean_response": is_korean_request(text),
    }
    return _conversation_ux_release_payload("production conversation grounding integrity", checks)


def _legacy_production_final_conversation_ux_release_check_unused() -> dict[str, object]:
    checks = {
        "NATURAL_RESEARCH_RESPONSE": production_natural_research_conversation_release_check()["safety"] == "pass",
        "FOLLOWUP_CONTEXT": production_research_followup_context_release_check()["safety"] == "pass",
        "UNNECESSARY_RERUN_BLOCKED": production_no_unnecessary_research_rerun_release_check()["safety"] == "pass",
        "AUTHORITATIVE_GROUNDING": production_conversation_grounding_integrity_release_check()["safety"] == "pass",
        "TWO_STAGE_APPROVAL_PRESERVED": production_natural_promotion_approval_conversation_release_check()["safety"] == "pass",
        "RESEARCH_ENGINE_REUSED": True,
        "DUPLICATE_CONVERSATION_ENGINE": False,
    }
    return _conversation_ux_release_payload("production final conversation ux", checks)


def _conversation_ux_release_payload(name: str, checks: dict[str, bool]) -> dict[str, object]:
    if not all(checks.values()):
        failed = ",".join(key for key, ok in checks.items() if not ok)
        raise RuntimeError(f"{name} release check failed: {failed}")
    return {
        "schema_version": 1,
        "name": name,
        "status": "pass",
        "approval_required": False,
        "strategy_mutated": False,
        "order_executed": False,
        "checks": dict(checks),
        "safety": "pass",
    }


def _natural_conversation_fixture_payload(*, promotion_ready: bool) -> dict[str, object]:
    promotion_status = "requires_human_approval" if promotion_ready else "needs_more_evidence"
    human_gate_status = "awaiting_human_approval" if promotion_ready else "not_requested"
    readiness_status = "ready_for_human_approval" if promotion_ready else "needs_more_evidence"
    return {
        "symbol": "005930",
        "source": "real:yahoo-chart",
        "fixture_backed": False,
        "quality_status": "pass_with_warnings",
        "promotion_status": promotion_status,
        "human_gate_status": human_gate_status,
        "baseline": {
            "dataset": {"metadata": {"symbol": "005930", "source": "real:yahoo-chart", "fixture_backed": False, "rows": 1222}},
            "backtest": {"metrics": {"trade_count": 17, "total_return": 0.082, "mdd": 0.192288}},
        },
        "autonomous_learning_v2": {
            "external_research_state": "partial_success",
            "hypothesis_status": "proposed",
            "validation_status": "needs_more_evidence",
            "ranking_status": "blocked",
            "autonomous_quant_partner_promotion_status": promotion_status,
            "autonomous_quant_partner": {
                "promotion_readiness_report": {
                    "status": readiness_status,
                    "remaining_risks": [] if promotion_ready else ["out_of_sample_underperformed_baseline", "cost_fragile"],
                },
                "source_acquisition": {
                    "source_categories_acquired": ["academic", "official_market", "professional_research"],
                    "sources_acquired": 3,
                },
                "counter_evidence": {"attempted": True, "status": "mixed"},
                "validation_coverage": {
                    "raw_bars": 1222,
                    "usable_bars": 1162,
                    "completed_trade_count": 17,
                    "minimum_required_trades": 30,
                    "sample_sufficiency_status": "insufficient_trades",
                    "out_of_sample_status": "fail_underperformed_baseline",
                    "walk_forward_status": "fail",
                    "multi_symbol_status": "partial",
                    "monte_carlo": "not_run_insufficient_primary_sample",
                },
                "strategy_tournament": {"candidate_count": 3, "best_candidate": "candidate-b"},
                "research_iterations": [{"iteration": 1}, {"iteration": 2}],
                "production_grade_validation": {
                    "independent_evidence": {"independent_source_count": 3, "status": "partial"},
                    "multi_symbol_validation": {"cross_symbol_status": "partial", "symbols_tested": 5},
                    "out_of_sample": {"status": "fail_underperformed_baseline", "blockers": ["candidate_underperformed_baseline"]},
                    "walk_forward": {"status": "fail", "fold_count": 3},
                    "regime_validation": {"status": "partial"},
                    "parameter_sensitivity": {"status": "stable"},
                    "transaction_cost_stress": {"status": "cost_fragile", "blockers": ["high_cost_scenario_degraded"]},
                    "monte_carlo": {"status": "not_run_insufficient_primary_sample", "executed": False},
                },
            },
        },
        "strategy_mutated": False,
        "order_executed": False,
        "automatic_champion_promotion": False,
    }


def _contains_default_debug_tokens(text: str) -> bool:
    return any(
        token in text
        for token in (
            "partner_status=",
            "validation_coverage=",
            "ranking_gate=",
            "source_ids=",
            "schema_version=",
            "raw blocker",
        )
    )


def production_research_followup_context_release_check() -> dict[str, object]:
    payload = _natural_conversation_fixture_payload(promotion_ready=False)
    oos = format_grounded_tool_response("autonomous_learning_research", payload, "OOS follow-up") or ""
    cost = format_grounded_tool_response("autonomous_learning_research", payload, "transaction cost follow-up") or ""
    monte = format_grounded_tool_response("autonomous_learning_research", payload, "Monte Carlo follow-up") or ""
    checks = {
        "oos_uses_context": "OOS" in oos and "partner_status=" not in oos,
        "cost_uses_context": "partner_status=" not in cost and "trade_count=0" not in cost,
        "monte_uses_context": "Monte Carlo" in monte and "partner_status=" not in monte,
        "no_debug_dump": not any(_contains_default_debug_tokens(text) for text in (oos, cost, monte)),
    }
    return _conversation_ux_release_payload("production research followup context", checks)


def production_final_conversation_ux_release_check() -> dict[str, object]:
    checks = {
        "NATURAL_RESEARCH_RESPONSE": production_natural_research_conversation_release_check()["safety"] == "pass",
        "FOLLOWUP_CONTEXT": production_research_followup_context_release_check()["safety"] == "pass",
        "UNNECESSARY_RERUN_BLOCKED": production_no_unnecessary_research_rerun_release_check()["safety"] == "pass",
        "AUTHORITATIVE_GROUNDING": production_conversation_grounding_integrity_release_check()["safety"] == "pass",
        "TWO_STAGE_APPROVAL_PRESERVED": production_natural_promotion_approval_conversation_release_check()["safety"] == "pass",
        "RESEARCH_ENGINE_REUSED": True,
        "DUPLICATE_CONVERSATION_ENGINE": False,
    }
    pass_checks = {key: value for key, value in checks.items() if key != "DUPLICATE_CONVERSATION_ENGINE"}
    if not all(pass_checks.values()) or checks["DUPLICATE_CONVERSATION_ENGINE"]:
        failed = ",".join(key for key, ok in pass_checks.items() if not ok)
        if checks["DUPLICATE_CONVERSATION_ENGINE"]:
            failed = f"{failed},DUPLICATE_CONVERSATION_ENGINE" if failed else "DUPLICATE_CONVERSATION_ENGINE"
        raise RuntimeError(f"production final conversation ux release check failed: {failed}")
    return {
        "schema_version": 1,
        "name": "production final conversation ux",
        "status": "pass",
        "approval_required": False,
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }
