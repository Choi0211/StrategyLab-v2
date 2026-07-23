"""Grounded research response helpers for conversational safe tools."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ResearchFact:
    name: str
    value: object
    source: str
    source_ref: str


FABRICATED_METRIC_TOKENS = (
    "1.35",
    "1.05",
    "64",
    "520",
    "14%",
    "0.14",
    "샤프 1.35",
    "샤프 1.05",
    "MDD 14",
    "거래 64",
    "샘플 520",
)


def is_research_tool(tool_name: str) -> bool:
    return tool_name in RESEARCH_TOOLS


def contains_unverified_fixture_metrics(text: str, facts: Iterable[ResearchFact] = ()) -> bool:
    allowed = {str(fact.value) for fact in facts}
    return any(token in text and token not in allowed for token in FABRICATED_METRIC_TOKENS)


def format_grounded_tool_response(tool_name: str, output: dict[str, object]) -> str | None:
    if tool_name == "research_memory_search":
        return _format_memory(output)
    if tool_name == "strategy_critique":
        return _format_strategy_critique(output)
    if tool_name == "strategy_quality_score":
        return _format_quality(output)
    if tool_name == "data_quality_check":
        return _format_data_quality(output)
    if tool_name == "backtest_strategy":
        return _format_backtest(output.get("result"), output)
    if tool_name == "backtest_result":
        return _format_backtest(output.get("result"), output)
    if tool_name == "compare_backtests":
        return _format_comparison(output)
    return None


def grounded_system_policy() -> str:
    return (
        "For research or strategy claims, use only user-provided facts or verified safe-tool results. "
        "Never invent Sharpe, MDD, trade count, sample size, dates, or backtest metrics. "
        "If a metric is unavailable, say it is unavailable. "
        "Separate verified data, qualitative analysis, and hypotheses. "
        "Disclose fixture-backed data as fixtures and do not label it real historical data."
    )


def _format_memory(output: dict[str, object]) -> str:
    count = int(output.get("count", 0) or 0)
    if count <= 0:
        return (
            "영하님, 연구 메모리를 검색했지만 저장된 유사 연구 기록을 찾지 못했습니다.\n"
            "검증된 데이터: 검색 도구는 정상 동작했고 결과 수는 0건입니다.\n"
            "정성 분석: 아직 저장된 매칭 기록이 없다는 뜻입니다.\n"
            "가설/제안: 현재 전략 조건을 기준으로 새 연구 기록을 만들거나 백테스트 결과를 먼저 연결할 수 있습니다."
        )
    results = output.get("results")
    lines = [f"영하님, 저장된 연구 메모리에서 {count}건을 찾았습니다.", "검증된 데이터:"]
    if isinstance(results, list):
        for item in results[:3]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('memory_id') or item.get('run_id') or 'memory'} / {item.get('strategy_family') or item.get('family') or 'unknown'}")
    lines.append("정성 분석: 위 항목은 저장된 연구 기억을 기준으로만 요약했습니다.")
    return "\n".join(lines)


def _format_strategy_critique(output: dict[str, object]) -> str:
    critique = output.get("critique")
    plan = output.get("improvement_plan")
    provider = output.get("provider", "unknown")
    lines = [
        "영하님, 이 전략은 현재 검증 수치가 아니라 안전 도구의 fixture 기반 정성 평가로만 살펴봤습니다.",
        "검증된 데이터:",
        f"- data_source={provider}",
        "- fixture_backed=true",
        "- 실제 백테스트 성과 지표는 이 응답에서 확인되지 않았습니다.",
        "정성 분석:",
    ]
    if isinstance(critique, dict):
        findings = critique.get("findings")
        if isinstance(findings, list) and findings:
            for finding in findings[:4]:
                if isinstance(finding, dict):
                    lines.append(f"- {finding.get('severity', 'unknown')}: {finding.get('message', 'finding')}")
    lines.append("가설/개선 제안:")
    if isinstance(plan, dict):
        steps = plan.get("steps") or plan.get("actions")
        if isinstance(steps, list) and steps:
            for step in steps[:4]:
                if isinstance(step, dict):
                    lines.append(f"- {step.get('description', '검증 조건을 보완합니다.')}")
                else:
                    lines.append(f"- {step}")
        else:
            updates = plan.get("parameter_updates")
            if isinstance(updates, dict) and updates:
                lines.append(f"- 조건 변경 후보: {', '.join(sorted(str(key) for key in updates))}")
    if lines[-1] == "가설/개선 제안:":
        lines.append("- 워크포워드 검증, 비용 가정, 표본 안정성 검사를 다음 단계로 연결하는 것이 안전합니다.")
    lines.append("자동 승인이나 Champion 승격은 수행하지 않았습니다.")
    return "\n".join(lines)


def _format_quality(output: dict[str, object]) -> str:
    quality = output.get("quality")
    provider = output.get("provider", "unknown")
    lines = ["영하님, 전략 품질 점수는 도구가 반환한 품질 필드만 사용해 설명하겠습니다.", "검증된 데이터:", f"- data_source={provider}"]
    if isinstance(quality, dict):
        total = quality.get("total")
        if total is not None:
            lines.append(f"- total={total}")
        components = quality.get("components")
        if isinstance(components, dict):
            for key in sorted(components)[:10]:
                lines.append(f"- {key}={components[key]}")
    lines.extend(
        (
            "정성 분석: 위 점수는 품질 스코어 계약의 구성 요소이며, 별도 백테스트 성과 수치로 해석하지 않습니다.",
            "가설/제안: 낮은 구성 요소부터 검증 계획을 세우되 자동 승격은 하지 않습니다.",
        )
    )
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
        "영하님, 데이터 품질 확인 결과입니다.\n"
        "검증된 데이터:\n"
        f"- dataset_id={dataset_id}\n"
        f"- data_source={source}\n"
        f"- fixture_backed={fixture_backed}\n"
        f"- quality_status={status}\n"
        "정성 분석: fixture_backed=true이면 실제 시장 데이터가 아니라 테스트 fixture입니다.\n"
        "가설/제안: 실데이터 연결 전에는 이 결과를 운영 성과로 해석하지 않는 것이 안전합니다."
    )


def _format_backtest(result_obj: object, output: dict[str, object]) -> str:
    if not isinstance(result_obj, dict):
        return "영하님, 요청한 백테스트 결과를 찾지 못했습니다. 저장된 결과 ID를 다시 확인해 주세요."
    metrics = result_obj.get("metrics")
    provenance = result_obj.get("provenance")
    source = result_obj.get("source", "unknown")
    lines = ["영하님, 백테스트 결과는 반환된 결과 객체의 수치만 사용해 요약하겠습니다.", "검증된 데이터:", f"- validation_backend={source}"]
    if isinstance(provenance, dict):
        lines.append(f"- dataset_id={provenance.get('dataset_id', 'unknown')}")
        lines.append(f"- fixture_backed={str(provenance.get('fixture_backed', 'unknown')).lower()}")
    if isinstance(metrics, dict):
        for key in ("total_return", "cagr", "mdd", "win_rate", "profit_factor", "trade_count", "expectancy", "sharpe"):
            if key in metrics:
                lines.append(f"- {key}={metrics[key]}")
    lines.extend(
        (
            "정성 분석: fixture_backed=true이면 실제 시장 성과가 아니라 deterministic fixture 검증입니다.",
            "가설/제안: 실데이터, 비용, 워크포워드, 몬테카를로 검증 전에는 Champion 승격 근거로 사용하지 않습니다.",
        )
    )
    return "\n".join(lines)


def _format_comparison(output: dict[str, object]) -> str:
    comparison = output.get("comparison")
    lines = ["영하님, 비교 결과는 도구가 반환한 delta 필드만 기준으로 정리합니다.", "검증된 데이터:"]
    if isinstance(comparison, dict):
        deltas = comparison.get("metric_deltas")
        if isinstance(deltas, dict):
            for key in sorted(deltas):
                lines.append(f"- {key}_delta={deltas[key]}")
        winner = comparison.get("winner")
        if winner is not None:
            lines.append(f"- winner={winner}")
    lines.append("정성 분석: 이 비교는 fixture 계약 검증이며 자동 승인이나 배포를 수행하지 않습니다.")
    return "\n".join(lines)
