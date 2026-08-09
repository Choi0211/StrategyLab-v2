"""Telegram-facing Autonomous Learning V2 production orchestration.

The Telegram safe tool must not call deterministic release-check fixtures. This
module starts from the production KRX real-research payload and only promotes
candidate evidence that was produced by the existing real research/backtest
engine. Fixture evidence is allowed in release checks elsewhere, but is
fail-closed here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from typing import Mapping

from gaon.storage.foundation import GaonStorage

from .discovery_ingestion import DiscoveryEvidenceIngestor
from .execution import (
    DEFAULT_ALLOWED_API_HOSTS,
    BoundedSourceDiscoveryExecutor,
    JsonTransport,
    NetworkExecutionPolicy,
)
from .external_research_execution import (
    AutonomousExternalResearchExecutor,
    ExternalResearchExecutionPolicy,
    ExternalResearchTerminalState,
)
from .conflicts import ConflictStatus
from .gaps import (
    KnowledgeGapType,
    RequiredEvidence,
    RequiredEvidenceType,
    ResearchPriority,
    ResearchQuestion,
    ResearchStopCondition,
)
from .promotion_gate import PromotionCandidateGate, PromotionGateStatus
from .robustness_ranking import StrategyRobustnessRanker
from .strategy_experiment import StrategyExperimentStatus, StrategyResearchExperiment
from .validation_loop_v2 import AuthoritativeValidationEvidence, AutonomousValidationLoopV2


TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION = 2
PRODUCTION_EXTERNAL_DISCOVERY_TIMEOUT_SECONDS = 10.0
PRODUCTION_EXTERNAL_DISCOVERY_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PRODUCTION_EXTERNAL_DISCOVERY_MAX_PROVIDER_CALLS = 1
PRODUCTION_EXTERNAL_DISCOVERY_MAX_SOURCES = 1


def telegram_autonomous_learning_payload(
    connection: sqlite3.Connection,
    request_text: str,
    *,
    symbol: str = "005930",
    mode: str = "research",
    storage_root: str | None = None,
) -> Mapping[str, object]:
    """Run the production Autonomous Learning V2 route behind Telegram."""

    from gaon.research.krx_real_pipeline import krx_real_research_payload

    baseline = krx_real_research_payload(connection, request_text, symbol=symbol)
    external = _run_production_external_research(
        request_text,
        symbol=symbol,
        storage_root=storage_root,
    )
    return production_autonomous_learning_payload_from_baseline(
        request_text,
        symbol=symbol,
        mode=mode,
        baseline=baseline,
        external_research=external,
    )


def production_autonomous_learning_payload_from_baseline(
    request_text: str,
    *,
    symbol: str,
    mode: str,
    baseline: Mapping[str, object],
    external_research: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Build a production payload from authoritative real-research output.

    This helper is intentionally fixture-free. Tests can pass synthetic
    authoritative baseline payloads, but promotion eligibility still depends on
    explicit `fixture_backed=false` and matching candidate strategy fingerprints.
    """

    dataset = _as_dict(baseline.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    quality = _as_dict(baseline.get("quality"))
    baseline_backtest = _as_dict(baseline.get("backtest"))
    baseline_strategy = _as_dict(baseline.get("strategy"))
    candidate = _select_candidate(baseline)
    candidate_backtest = _as_dict(candidate.get("backtest_result"))
    candidate_strategy = _as_dict(candidate.get("strategy"))
    external = dict(external_research or _empty_external_research(symbol))

    baseline_fixture = bool(
        metadata.get("fixture_backed")
        or baseline.get("fixture_backed")
        or baseline_backtest.get("source") == "fixture"
    )
    candidate_fixture = bool(
        candidate_backtest.get("source") != "real"
        or not candidate_backtest
        or _as_dict(candidate_backtest.get("strategy")).get("fingerprint") != candidate_strategy.get("fingerprint")
    )
    external_ready = external.get("state") == ExternalResearchTerminalState.EVIDENCE_SUFFICIENT.value

    experiment = _build_candidate_experiment(
        symbol=symbol,
        baseline_strategy=baseline_strategy,
        candidate=candidate,
        candidate_backtest=candidate_backtest,
        metadata=metadata,
    )
    evidence = _candidate_evidence(experiment, candidate_backtest, quality)
    validation = AutonomousValidationLoopV2().assess(experiment, evidence)
    ranking = StrategyRobustnessRanker().rank((validation,))
    promotion = PromotionCandidateGate().evaluate(
        ranking,
        rollback_target="strategy-config:default:active",
        allow_fixture=False,
    )
    production_blockers = _production_blockers(
        baseline_fixture=baseline_fixture,
        candidate_fixture=candidate_fixture,
        external_ready=external_ready,
        candidate=candidate,
        experiment=experiment,
        evidence=evidence,
        promotion_status=promotion.status.value,
    )
    promotion_status = promotion.status.value
    human_gate_status = "awaiting_human_approval" if promotion.status is PromotionGateStatus.REQUIRES_HUMAN_APPROVAL else "not_requested"
    if production_blockers:
        promotion_status = "blocked_fixture" if any("fixture" in item for item in production_blockers) else "needs_real_validation"
        human_gate_status = "not_requested"

    learning = {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "external_research_state": external.get("state", "unknown"),
        "hypothesis_status": "proposed" if candidate else "blocked",
        "validation_status": validation.status.value,
        "ranking_status": ranking.status.value,
        "promotion_status": promotion_status,
        "human_gate_status": human_gate_status,
        "production_uses_release_fixture": False,
        "fixture_promotion_blocked": bool(production_blockers),
        "candidate_backtest_authoritative": bool(evidence and candidate_backtest),
        "candidate_strategy_fingerprint_matched": bool(
            candidate_strategy.get("fingerprint")
            and _as_dict(candidate_backtest.get("strategy")).get("fingerprint") == candidate_strategy.get("fingerprint")
        ),
        "candidate_backtest_executed": bool(candidate_backtest),
        "real_data_required": True,
        "blockers": production_blockers,
        "external_research": external,
        "validation": validation.to_json(),
        "ranking": ranking.to_json(),
        "promotion_candidate": promotion.to_json(),
        "promotion_candidate_context": _promotion_candidate_context(
            symbol=symbol,
            baseline=baseline,
            candidate=candidate,
            experiment=experiment,
            evidence=evidence,
            validation=validation.to_json(),
            ranking=ranking.to_json(),
            promotion=promotion.to_json(),
            external_research=external,
            promotion_status=promotion_status,
            human_gate_status=human_gate_status,
            blockers=production_blockers,
        ),
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
    }
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "tool": "autonomous_learning_research",
        "mode": mode,
        "symbol": symbol,
        "request_text": request_text,
        "baseline": dict(baseline),
        "autonomous_learning_v2": learning,
        "selected_orchestration": "autonomous_learning_v2",
        "source": metadata.get("source") or baseline_backtest.get("source") or "unknown",
        "fixture_backed": baseline_fixture,
        "quality_status": quality.get("status", "unknown"),
        "approval_required": promotion_status == "requires_human_approval",
        "promotion_status": promotion_status,
        "human_gate_status": human_gate_status,
        "production_uses_release_fixture": False,
        "fixture_promotion_blocked": bool(production_blockers),
        "candidate_backtest_authoritative": bool(evidence and candidate_backtest),
        "candidate_strategy_fingerprint_matched": learning["candidate_strategy_fingerprint_matched"],
        "real_data_required": True,
        "strategy_mutated": False,
        "order_executed": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
    }


def autonomous_learning_safe_failure_payload(
    request_text: str,
    *,
    symbol: str = "005930",
    mode: str = "research",
    error_type: str = "tool_failure",
    message: str = "",
) -> Mapping[str, object]:
    """Return the stable production safety contract for failed tool execution."""

    external = {
        "schema_version": 1,
        "state": ExternalResearchTerminalState.PROVIDER_FAILURE.value,
        "question_id": f"research-question:{symbol}:production-tool-failure",
        "discovery_run": None,
        "normalized_records": [],
        "candidates": [],
        "blockers": [f"tool_failure:{error_type}"],
        "network_executed": False,
        "observability": {
            "network_enabled": None,
            "network_executed": False,
            "provider_calls": 0,
            "failure_kind": error_type,
            "terminal_state": "provider_failure",
        },
    }
    learning = {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "external_research_state": external["state"],
        "hypothesis_status": "blocked",
        "validation_status": "unavailable",
        "ranking_status": "blocked",
        "promotion_status": "needs_real_validation",
        "human_gate_status": "not_requested",
        "production_uses_release_fixture": False,
        "fixture_promotion_blocked": True,
        "candidate_backtest_authoritative": False,
        "candidate_strategy_fingerprint_matched": False,
        "candidate_backtest_executed": False,
        "real_data_required": True,
        "blockers": list(external["blockers"]),
        "external_research": external,
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
    }
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "tool": "autonomous_learning_research",
        "mode": mode,
        "symbol": symbol,
        "request_text": request_text,
        "baseline": {},
        "autonomous_learning_v2": learning,
        "selected_orchestration": "autonomous_learning_v2",
        "source": "unavailable",
        "fixture_backed": False,
        "quality_status": "unavailable",
        "approval_required": False,
        "promotion_status": "needs_real_validation",
        "human_gate_status": "not_requested",
        "production_uses_release_fixture": False,
        "fixture_promotion_blocked": True,
        "candidate_backtest_authoritative": False,
        "candidate_strategy_fingerprint_matched": False,
        "real_data_required": True,
        "strategy_mutated": False,
        "order_executed": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
        "error_type": error_type,
        "message": message,
    }


def production_autonomous_learning_execution_release_check() -> Mapping[str, object]:
    real_payload = production_autonomous_learning_payload_from_baseline(
        "삼성전자 전략을 처음부터 다시 연구해줘",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=_release_external_ready(),
    )
    fixture_payload = production_autonomous_learning_payload_from_baseline(
        "삼성전자 전략을 처음부터 다시 연구해줘",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="fixture"),
        external_research=_release_external_ready(),
    )
    real_learning = _as_dict(real_payload.get("autonomous_learning_v2"))
    fixture_learning = _as_dict(fixture_payload.get("autonomous_learning_v2"))
    context = _as_dict(real_learning.get("promotion_candidate_context"))
    source_lineage = _as_list(context.get("source_lineage"))
    checks = {
        "production_uses_release_fixture": real_payload.get("production_uses_release_fixture") is False,
        "fixture_promotion_blocked": fixture_payload.get("fixture_promotion_blocked") is True and fixture_payload.get("approval_required") is False,
        "candidate_backtest_authoritative": real_payload.get("candidate_backtest_authoritative") is True,
        "candidate_strategy_fingerprint_matched": real_payload.get("candidate_strategy_fingerprint_matched") is True,
        "real_data_required": real_payload.get("real_data_required") is True,
        "no_example_fixture_source": "example.org" not in json.dumps(real_payload, ensure_ascii=False).lower()
        and not any("Fixture research" in json.dumps(item, ensure_ascii=False) for item in source_lineage),
        "no_mutation": not real_payload.get("strategy_mutated")
        and not real_payload.get("order_executed")
        and not real_payload.get("broker_order_called")
        and not real_payload.get("kis_order_called"),
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"production autonomous learning execution release check failed: {failed}")
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "production_uses_release_fixture": False,
        "fixture_promotion_blocked": True,
        "candidate_backtest_authoritative": True,
        "candidate_strategy_fingerprint_matched": True,
        "real_data_required": True,
        "promotion_status": real_payload.get("promotion_status"),
        "fixture_promotion_status": fixture_payload.get("promotion_status"),
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "checks": checks,
        "safety": "pass",
    }


def production_external_research_network_release_check() -> Mapping[str, object]:
    transport = _ReleaseMetadataTransport()
    with tempfile.TemporaryDirectory(prefix="gaon-production-external-network-release-") as tmp:
        external = _run_production_external_research(
            "?쇱꽦?꾩옄 ?꾨왂??泥섏쓬遺???ㅼ떆 ?곌뎄?댁쨾",
            symbol="005930",
            transport=transport,
            storage_root=tmp,
        )
    payload = production_autonomous_learning_payload_from_baseline(
        "?쇱꽦?꾩옄 ?꾨왂??泥섏쓬遺???ㅼ떆 ?곌뎄?댁쨾",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    discovery = _as_dict(external.get("discovery_run"))
    observability = _as_dict(external.get("observability"))
    checks = {
        "discovery_network_explicitly_enabled": observability.get("network_enabled") is True
        and discovery.get("network_enabled") is True,
        "provider_allowlist_preserved": tuple(observability.get("allowed_api_hosts") or ())
        == DEFAULT_ALLOWED_API_HOSTS,
        "metadata_discovery_executed": observability.get("network_executed") is True
        and int(observability.get("provider_calls") or 0) == 1
        and transport.calls == 1,
        "metadata_only_not_claimed_as_content": observability.get("content_acquisition_state") == "metadata_only"
        and int(external.get("acquired_sources") or 0) == 0
        and not external.get("candidates"),
        "content_unavailable_not_provider_failure": external.get("state") == ExternalResearchTerminalState.CONTENT_UNAVAILABLE.value,
        "fixture_promotion_blocked": payload.get("fixture_promotion_blocked") is True
        and learning.get("promotion_status") == "needs_real_validation",
        "no_mutation": not payload.get("strategy_mutated")
        and not payload.get("order_executed")
        and not payload.get("broker_order_called")
        and not payload.get("kis_order_called"),
        "no_fixture_lineage": "example.org" not in json.dumps(payload, ensure_ascii=False).lower()
        and "fixture research" not in json.dumps(payload, ensure_ascii=False).lower(),
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"production external research network release check failed: {failed}")
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "discovery_network_explicitly_enabled": True,
        "provider_allowlist_preserved": True,
        "metadata_discovery_executed": True,
        "metadata_only_not_claimed_as_content": True,
        "content_unavailable_not_provider_failure": True,
        "fixture_promotion_blocked": True,
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }


def _run_production_external_research(
    request_text: str,
    *,
    symbol: str,
    transport: JsonTransport | None = None,
    network_enabled: bool = True,
    storage_root: str | None = None,
) -> Mapping[str, object]:
    storage_root = storage_root or os.environ.get("GAON_EXTERNAL_RESEARCH_STORAGE_ROOT")
    question = ResearchQuestion(
        question_id=f"research-question:{_hash({'symbol': symbol, 'request_text': request_text})[:16]}",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question=f"{symbol} breakout strategy robustness evidence",
        priority=ResearchPriority.MEDIUM,
        required_evidence=(
            RequiredEvidence(
                evidence_type=RequiredEvidenceType.INDEPENDENT_SUPPORTING_SOURCE,
                minimum_independent_sources=1,
                rationale="Production promotion review requires non-fixture external evidence.",
            ),
        ),
        stop_conditions=(ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,),
        parent_conflict_id=f"knowledge-conflict:{_hash({'symbol': symbol, 'request_text': request_text})[:16]}",
        source_state=ConflictStatus.UNRESOLVED_CONFLICT,
    )
    network_policy = NetworkExecutionPolicy(
        network_enabled=network_enabled,
        allowed_api_hosts=DEFAULT_ALLOWED_API_HOSTS,
        timeout_seconds=PRODUCTION_EXTERNAL_DISCOVERY_TIMEOUT_SECONDS,
        max_response_bytes=PRODUCTION_EXTERNAL_DISCOVERY_MAX_RESPONSE_BYTES,
    )
    discovery_executor = BoundedSourceDiscoveryExecutor(
        network_policy=network_policy,
        transport=transport,
    )
    result = AutonomousExternalResearchExecutor(
        discovery_executor=discovery_executor,
        ingestion=(
            DiscoveryEvidenceIngestor(GaonStorage(storage_root))
            if storage_root
            else None
        ),
        policy=ExternalResearchExecutionPolicy(
            max_iterations=1,
            max_provider_calls=PRODUCTION_EXTERNAL_DISCOVERY_MAX_PROVIDER_CALLS,
            max_sources=PRODUCTION_EXTERNAL_DISCOVERY_MAX_SOURCES,
            content_network_enabled=False,
        )
    ).run(question)
    payload = result.to_json()
    if _network_disabled_discovery(payload):
        payload["state"] = "discovery_network_disabled"
        payload["blockers"] = list(_as_list(payload.get("blockers"))) + ["discovery_network_disabled"]
    payload["observability"] = _external_research_observability(
        payload,
        network_policy=network_policy,
    )
    return payload


def _external_research_observability(
    payload: Mapping[str, object],
    *,
    network_policy: NetworkExecutionPolicy,
) -> dict[str, object]:
    discovery = _as_dict(payload.get("discovery_run"))
    records = [_as_dict(item) for item in _as_list(discovery.get("query_records"))]
    results = [_as_dict(item) for item in _as_list(discovery.get("results"))]
    failure_kinds = [str(item.get("failure_kind")) for item in records if item.get("failure_kind")]
    content_blockers = [
        str(item)
        for item in _as_list(payload.get("blockers"))
        if str(item).startswith("content_unavailable")
    ]
    if not bool(discovery.get("network_enabled", network_policy.network_enabled)):
        terminal_state = "discovery_network_disabled"
    elif failure_kinds and not results:
        terminal_state = "provider_failure"
    elif content_blockers and not payload.get("candidates"):
        terminal_state = "metadata_only"
    else:
        terminal_state = str(payload.get("state") or "unknown")
    return {
        "network_enabled": bool(discovery.get("network_enabled", network_policy.network_enabled)),
        "network_executed": bool(payload.get("network_executed") or discovery.get("network_executed")),
        "provider_calls": int(payload.get("provider_calls") or discovery.get("provider_calls") or 0),
        "allowed_api_hosts": list(network_policy.allowed_api_hosts),
        "timeout_seconds": network_policy.timeout_seconds,
        "max_response_bytes": network_policy.max_response_bytes,
        "query_records": [
            {
                "provider": item.get("provider"),
                "returned_results": item.get("returned_results"),
                "accepted_results": item.get("accepted_results"),
                "failure_kind": item.get("failure_kind"),
                "error_message": item.get("error_message"),
            }
            for item in records
        ],
        "discovered_titles": [item.get("title") for item in results if item.get("title")],
        "locators": [item.get("locator") for item in results if item.get("locator")],
        "metadata_only": bool(results and not payload.get("normalized_records") and not payload.get("candidates")),
        "content_acquisition_state": "metadata_only" if content_blockers and not payload.get("candidates") else "not_attempted",
        "failure_kind": failure_kinds[0] if failure_kinds else None,
        "terminal_state": terminal_state,
    }


def _network_disabled_discovery(payload: Mapping[str, object]) -> bool:
    discovery = _as_dict(payload.get("discovery_run"))
    records = [_as_dict(item) for item in _as_list(discovery.get("query_records"))]
    return bool(records) and all(item.get("failure_kind") == "network_disabled" for item in records)


def _select_candidate(baseline: Mapping[str, object]) -> dict[str, object]:
    candidates = _as_list(baseline.get("candidates"))
    for item in candidates:
        candidate = _as_dict(item)
        if _as_dict(candidate.get("backtest_result")):
            return candidate
    return {}


def _build_candidate_experiment(
    *,
    symbol: str,
    baseline_strategy: Mapping[str, object],
    candidate: Mapping[str, object],
    candidate_backtest: Mapping[str, object],
    metadata: Mapping[str, object],
) -> StrategyResearchExperiment:
    candidate_strategy = _as_dict(candidate.get("strategy"))
    assumptions = _as_dict(candidate_backtest.get("assumptions"))
    changed_rules = tuple(str(item) for item in _as_list(candidate.get("changed_fields")) if str(item))
    if not changed_rules:
        changed_rules = ("unimplemented_changed_rule",)
    assumptions_fingerprint = _hash(assumptions)
    candidate_fingerprint = str(candidate_strategy.get("fingerprint") or "candidate:fingerprint:missing")
    return StrategyResearchExperiment(
        experiment_id=f"strategy-experiment:{_hash({'candidate': candidate_fingerprint, 'assumptions': assumptions_fingerprint, 'changed_rules': changed_rules})}",
        hypothesis_id=f"strategy-hypothesis:{_hash({'candidate': candidate_fingerprint, 'changed_rules': changed_rules})}",
        baseline_strategy_id=str(baseline_strategy.get("spec_id") or "strategy:baseline"),
        baseline_strategy_fingerprint=str(baseline_strategy.get("fingerprint") or "baseline:fingerprint:missing"),
        assumptions_fingerprint=assumptions_fingerprint,
        changed_rules=changed_rules,
        universe_symbols=(symbol,),
        start=str(metadata.get("start_date") or "unknown"),
        end=str(metadata.get("end_date") or "unknown"),
        cost_model="default_research_costs",
        status=StrategyExperimentStatus.READY_FOR_VALIDATION,
    )


def _candidate_evidence(
    experiment: StrategyResearchExperiment,
    candidate_backtest: Mapping[str, object],
    quality: Mapping[str, object],
) -> AuthoritativeValidationEvidence | None:
    if not candidate_backtest:
        return None
    metrics = _as_dict(candidate_backtest.get("metrics"))
    trade_count = int(metrics.get("trade_count") or 0)
    source = str(candidate_backtest.get("source") or "unknown")
    blocking = tuple(
        str(item.get("code", "quality_blocker"))
        for item in _as_list(quality.get("findings"))
        if isinstance(item, dict) and str(item.get("severity", "")).lower() in {"error", "critical", "blocking"}
    )
    return AuthoritativeValidationEvidence(
        evidence_id=f"validation-evidence:{_hash({'experiment_id': experiment.experiment_id, 'backtest_result_id': candidate_backtest.get('result_id'), 'fingerprint': candidate_backtest.get('fingerprint')})}",
        experiment_id=experiment.experiment_id,
        backtest_result_id=str(candidate_backtest.get("result_id") or "backtest:missing"),
        source="real:yahoo-chart" if source == "real" else f"fixture:{source}" if source == "fixture" else source,
        fixture_backed=source != "real",
        quality_status=str(quality.get("status") or "unknown"),
        blocking_findings=blocking,
        metrics=metrics,
        trade_count=trade_count,
        created_at=str(candidate_backtest.get("generated_at") or "2026-08-08T00:00:00+00:00"),
    )


def _production_blockers(
    *,
    baseline_fixture: bool,
    candidate_fixture: bool,
    external_ready: bool,
    candidate: Mapping[str, object],
    experiment: StrategyResearchExperiment,
    evidence: AuthoritativeValidationEvidence | None,
    promotion_status: str,
) -> list[str]:
    blockers: list[str] = []
    if baseline_fixture:
        blockers.append("baseline_fixture_backed")
    if candidate_fixture:
        blockers.append("candidate_fixture_or_fingerprint_mismatch")
    if not candidate:
        blockers.append("no_tested_candidate_backtest")
    if "unimplemented_changed_rule" in experiment.changed_rules:
        blockers.append("hypothesis_unexecutable")
    if evidence is None:
        blockers.append("missing_authoritative_candidate_backtest")
    if not external_ready:
        blockers.append("external_research_content_unavailable")
    if promotion_status == "blocked":
        blockers.append("promotion_gate_blocked")
    return list(dict.fromkeys(blockers))


def _promotion_candidate_context(
    *,
    symbol: str,
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
    experiment: StrategyResearchExperiment,
    evidence: AuthoritativeValidationEvidence | None,
    validation: Mapping[str, object],
    ranking: Mapping[str, object],
    promotion: Mapping[str, object],
    external_research: Mapping[str, object],
    promotion_status: str,
    human_gate_status: str,
    blockers: list[str],
) -> dict[str, object]:
    candidate_strategy = _as_dict(candidate.get("strategy"))
    source_lineage = _source_lineage(external_research)
    return {
        "candidate_id": promotion.get("candidate_id"),
        "candidate_fingerprint": candidate_strategy.get("fingerprint"),
        "baseline_strategy_id": _as_dict(baseline.get("strategy")).get("spec_id"),
        "baseline_fingerprint": _as_dict(baseline.get("strategy")).get("fingerprint"),
        "hypothesis": {
            "hypothesis_id": experiment.hypothesis_id,
            "topic_key": "strategy.breakout.robustness",
            "changed_rules": list(experiment.changed_rules),
            "rationale": "Production V2 can only review candidates with real external evidence and authoritative candidate backtests.",
            "mechanism": "Existing real KRX research generated and tested the candidate strategy before validation.",
            "falsification_criteria": ["Block if candidate backtest is fixture-backed, missing, or fingerprint-mismatched."],
        },
        "changed_rules": list(experiment.changed_rules),
        "rationale": "Production V2 can only review candidates with real external evidence and authoritative candidate backtests.",
        "expected_mechanism": "Candidate evidence is grounded in the existing KRX real-research backtest output.",
        "falsification_criteria": ["Reject if authoritative candidate metrics are missing or fixture-backed."],
        "research_memory": {"state": external_research.get("state"), "question_id": external_research.get("question_id")},
        "claim_ids": _claim_ids(external_research),
        "source_ids": _source_ids(external_research),
        "source_lineage": source_lineage,
        "experiment": experiment.to_json(),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": _hash(experiment.to_json()),
        "assumptions_fingerprint": experiment.assumptions_fingerprint,
        "authoritative_validation_evidence": evidence.to_json() if evidence else None,
        "authoritative_backtest_result_id": evidence.backtest_result_id if evidence else None,
        "validation": dict(validation),
        "ranking": dict(ranking),
        "ranking_components": _ranking_components(ranking),
        "blockers": blockers,
        "risks": blockers,
        "human_gate": {"status": human_gate_status, "approval_requested": human_gate_status == "awaiting_human_approval"},
        "approval_state": human_gate_status,
        "promotion_candidate": dict(promotion),
        "promotion_status": promotion_status,
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
    }


def _source_lineage(external_research: Mapping[str, object]) -> list[dict[str, object]]:
    discovery = _as_dict(external_research.get("discovery_run"))
    results = _as_list(discovery.get("results"))
    lineage: list[dict[str, object]] = []
    for result in results:
        row = _as_dict(result)
        if not row:
            continue
        lineage.append(
            {
                "title": row.get("title"),
                "source_type": row.get("source_type"),
                "locator": row.get("locator"),
                "source_ids": (),
                "claim_ids": (),
                "metadata_only": True,
                "content_acquired": False,
            }
        )
    return lineage


def _claim_ids(external_research: Mapping[str, object]) -> list[str]:
    return [
        str(item.get("candidate_id"))
        for item in _as_list(external_research.get("candidates"))
        if isinstance(item, dict) and item.get("candidate_id")
    ]


def _source_ids(external_research: Mapping[str, object]) -> list[str]:
    return [
        str(item.get("source_id"))
        for item in _as_list(external_research.get("candidates"))
        if isinstance(item, dict) and item.get("source_id")
    ]


def _ranking_components(ranking: Mapping[str, object]) -> dict[str, object]:
    ranked = _as_list(ranking.get("ranked"))
    top = _as_dict(ranked[0]) if ranked else {}
    return {
        key: value
        for key, value in top.items()
        if key in {"score", "trade_count", "total_return", "mdd", "profit_factor", "win_rate", "source", "fixture_backed", "rank"}
    }


def _empty_external_research(symbol: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": ExternalResearchTerminalState.CONTENT_UNAVAILABLE.value,
        "question_id": f"research-question:{symbol}:production-unavailable",
        "discovery_run": None,
        "normalized_records": [],
        "candidates": [],
        "blockers": ["content_unavailable"],
        "network_executed": False,
    }


class _ReleaseMetadataTransport:
    def __init__(self, *, mode: str = "crossref_metadata") -> None:
        self.mode = mode
        self.calls = 0
        self.urls: list[str] = []

    def get_json(self, url: str, *, policy: NetworkExecutionPolicy) -> Mapping[str, object]:
        from urllib.parse import urlparse

        self.calls += 1
        self.urls.append(url)
        host = (urlparse(url).hostname or "").lower()
        if host not in {item.lower() for item in DEFAULT_ALLOWED_API_HOSTS}:
            raise PermissionError(f"blocked host: {host}")
        if not policy.network_enabled:
            raise PermissionError("network execution is disabled")
        if self.mode == "provider_failure":
            raise TimeoutError("release transport timeout")
        if self.mode == "no_results":
            return {"message": {"items": []}}
        return {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/gaon-production-metadata",
                        "title": ["Breakout robustness metadata"],
                        "type": "journal-article",
                        "URL": "https://doi.org/10.1234/gaon-production-metadata",
                    }
                ]
            }
        }


def _release_baseline_payload(*, source: str) -> dict[str, object]:
    fixture = source != "real"
    candidate_strategy = {
        "schema_version": 1,
        "spec_id": "strategy:005930:candidate",
        "symbol": "005930",
        "entry": {"breakout_lookback": {"value": 30, "provenance": "research_candidate"}},
        "exit": {"channel_exit_lookback": {"value": 10, "provenance": "user_provided"}},
        "filters": {"volume_gte_ma20": {"value": True, "provenance": "user_provided"}},
        "source_text": "release-check candidate",
        "created_at": "2026-08-08T00:00:00+00:00",
        "fingerprint": "candidate-fingerprint-release-1854",
    }
    assumptions = {
        "commission": {"value": 0.00015, "provenance": "default"},
        "tax": {"value": 0.0018, "provenance": "default"},
        "slippage": {"value": 0.0005, "provenance": "default"},
        "execution_timing": {"value": "next_open", "provenance": "default"},
        "position_sizing": {"value": "all_in", "provenance": "default"},
        "initial_capital": {"value": 1000000, "provenance": "default"},
    }
    candidate_backtest = {
        "schema_version": 1,
        "result_id": "backtest:release-1854:candidate",
        "run_id": "run:release-1854:candidate",
        "status": "completed",
        "source": source,
        "strategy": candidate_strategy,
        "dataset_id": "dataset:005930:release-1854",
        "dataset_fingerprint": "d" * 64,
        "assumptions": assumptions,
        "metrics": {
            "total_return": 0.18,
            "cagr": 0.035,
            "mdd": 0.09,
            "sharpe": 0.72,
            "win_rate": 0.56,
            "profit_factor": 1.6,
            "trade_count": 60,
            "average_trade": 0.003,
            "average_win": 0.012,
            "average_loss": -0.008,
            "payoff_ratio": 1.5,
            "exposure": 0.42,
            "ending_equity": 1180000.0,
            "expectancy": 0.003,
            "longest_losing_streak": 3,
        },
        "trades": [],
        "equity_curve": [],
        "warnings": [],
        "generated_at": "2026-08-08T00:00:00+00:00",
        "fingerprint": "candidate-backtest-fingerprint-release-1854",
    }
    return {
        "schema_version": 1,
        "report_id": "krx-real-research-report:release-1854",
        "run_id": "krx-real-research:release-1854",
        "request_text": "삼성전자 전략을 처음부터 다시 연구해줘",
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart" if not fixture else "fixture:krx-real-pipeline",
                "fixture_backed": fixture,
                "start_date": "2021-07-25",
                "end_date": "2026-07-24",
                "rows": 1200,
            }
        },
        "quality": {"status": "pass", "findings": []},
        "strategy": {
            "spec_id": "strategy:005930:baseline",
            "fingerprint": "baseline-fingerprint-release-1854",
        },
        "assumptions": assumptions,
        "backtest": {
            **candidate_backtest,
            "result_id": "backtest:release-1854:baseline",
            "strategy": {
                **candidate_strategy,
                "spec_id": "strategy:005930:baseline",
                "fingerprint": "baseline-fingerprint-release-1854",
            },
        },
        "candidates": [
            {
                "candidate_id": "candidate:release-1854",
                "parent_strategy_id": "strategy:005930:baseline",
                "strategy": candidate_strategy,
                "changed_fields": ["entry.breakout_lookback"],
                "reason_ko": "후보 전략은 기존 real research candidate backtest 결과만 사용합니다.",
                "provenance": "research_candidate",
                "backtest_result": candidate_backtest,
            }
        ],
    }


def _release_external_ready() -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": ExternalResearchTerminalState.EVIDENCE_SUFFICIENT.value,
        "question_id": "research-question:release-1854",
        "discovery_run": {
            "results": [
                {
                    "result_id": "discovery:release-1854",
                    "title": "Bounded production metadata",
                    "source_type": "research_report",
                    "locator": "https://doi.org/10.0000/strategylab-release-1854",
                }
            ]
        },
        "normalized_records": [],
        "candidates": [{"candidate_id": "claim:release-1854", "source_id": "source:release-1854"}],
        "blockers": [],
        "network_executed": False,
    }


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
