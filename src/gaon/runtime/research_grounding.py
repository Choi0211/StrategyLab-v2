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
                    lines.append(f"- {_ko(action.get('description', '\uac80\uc99d \uc870\uac74\uc744 \ubcf4\uc644\ud569\ub2c8\ub2e4.'))}")
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
