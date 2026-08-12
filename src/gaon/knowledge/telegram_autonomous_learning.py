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
from urllib.error import HTTPError

from gaon.storage.foundation import GaonStorage

from .content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionPolicy,
    FetchPayload,
    HttpsBinaryTransport,
)
from .discovery import DiscoveryBudget, SourceDiscoveryPlanner
from .discovery_ingestion import DiscoveryEvidenceIngestor
from .execution import (
    DEFAULT_ALLOWED_API_HOSTS,
    BoundedSourceDiscoveryExecutor,
    JsonTransport,
    NetworkExecutionPolicy,
)
from .external_research_execution import (
    AcademicContentResolver,
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
PRODUCTION_EXTERNAL_DISCOVERY_MAX_CANDIDATE_RESULTS = 5
PRODUCTION_EXTERNAL_RELEVANT_CANDIDATES = 5
PRODUCTION_EXTERNAL_RESOLUTION_ATTEMPTS = 3
PRODUCTION_EXTERNAL_CONTENT_ACQUISITION_ATTEMPTS = 3
PRODUCTION_EXTERNAL_MAX_ACQUIRED_SOURCES = 2
PRODUCTION_EXTERNAL_MAX_GROUNDED_SOURCES = 2
PRODUCTION_EXTERNAL_CONTENT_TIMEOUT_SECONDS = 12.0
PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES = 256 * 1024
PRODUCTION_EXTERNAL_CONTENT_ALLOWED_HOSTS = (
    "doi.org",
    "arxiv.org",
    "export.arxiv.org",
    "zenodo.org",
    "figshare.com",
    "www.nber.org",
)
PRODUCTION_EXTERNAL_ALLOWED_CONTENT_TYPES = (
    "text/plain",
    "text/html",
    "application/json",
    "application/pdf",
)
PRODUCTION_AUTONOMOUS_LEARNING_MAX_HYPOTHESES = 3
PRODUCTION_AUTONOMOUS_LEARNING_MAX_EXPERIMENTS = 3


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
    grounded_evidence = _grounded_evidence_records(external)
    hypotheses = _evidence_backed_hypotheses(
        grounded_evidence,
        baseline_strategy=baseline_strategy,
        candidate=candidate,
        symbol=symbol,
    )

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
    external_ready = bool(grounded_evidence) and external.get("state") in {
        ExternalResearchTerminalState.EVIDENCE_SUFFICIENT.value,
        ExternalResearchTerminalState.UNRESOLVED_CONFLICT.value,
    }

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
    candidate_experiments = _candidate_experiment_records(
        hypotheses,
        experiment=experiment,
        candidate=candidate,
        candidate_backtest=candidate_backtest,
        metadata=metadata,
    )
    authoritative_validation = _authoritative_candidate_validation(
        experiment=experiment,
        evidence=evidence,
        validation=validation.to_json(),
        candidate=candidate,
        candidate_backtest=candidate_backtest,
    )
    production_blockers.extend(
        _production_loop_blockers(
            grounded_evidence=grounded_evidence,
            hypotheses=hypotheses,
            candidate_experiments=candidate_experiments,
            authoritative_validation=authoritative_validation,
            ranking=ranking.to_json(),
        )
    )
    production_blockers = list(dict.fromkeys(production_blockers))
    promotion_status = promotion.status.value
    human_gate_status = "awaiting_human_approval" if promotion.status is PromotionGateStatus.REQUIRES_HUMAN_APPROVAL else "not_requested"
    if production_blockers:
        promotion_status = "blocked_fixture" if _has_fixture_blocker(production_blockers) else "needs_real_validation"
        human_gate_status = "not_requested"
    hypothesis_status = "proposed" if hypotheses else "needs_evidence" if not grounded_evidence else "not_generated"

    learning = {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "external_research_state": external.get("state", "unknown"),
        "hypothesis_status": hypothesis_status,
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
        "grounded_evidence": grounded_evidence,
        "hypotheses": hypotheses,
        "candidate_experiments": candidate_experiments,
        "authoritative_candidate_validation": authoritative_validation,
        "validation": validation.to_json(),
        "ranking": ranking.to_json(),
        "promotion_candidate": promotion.to_json(),
        "production_loop": _production_loop_summary(
            grounded_evidence=grounded_evidence,
            hypotheses=hypotheses,
            candidate_experiments=candidate_experiments,
            authoritative_validation=authoritative_validation,
            ranking=ranking.to_json(),
            promotion_status=promotion_status,
            human_gate_status=human_gate_status,
            blockers=production_blockers,
        ),
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
            grounded_evidence=grounded_evidence,
            hypotheses=hypotheses,
            candidate_experiments=candidate_experiments,
            authoritative_candidate_validation=authoritative_validation,
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
            content_network_enabled=False,
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


def production_safe_content_acquisition_release_check() -> Mapping[str, object]:
    transport = _ReleaseMetadataTransport(mode="direct_content")
    content_transport = _ReleaseContentTransport()
    with tempfile.TemporaryDirectory(prefix="gaon-production-safe-content-release-") as tmp:
        external = _run_production_external_research(
            "Samsung breakout strategy external evidence safe content acquisition",
            symbol="005930",
            transport=transport,
            content_transport=content_transport,
            allowed_content_hosts=("content.example.org",),
            storage_root=tmp,
        )
    payload = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy external evidence safe content acquisition",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    fixture_payload = production_autonomous_learning_payload_from_baseline(
        "fixture evidence remains blocked",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="fixture"),
        external_research=external,
    )
    observability = _as_dict(external.get("observability"))
    content_sources = [_as_dict(item) for item in _as_list(observability.get("content_sources"))]
    first_source = content_sources[0] if content_sources else {}
    checks = {
        "allowed_content_acquired": external.get("state") in {
            ExternalResearchTerminalState.EVIDENCE_SUFFICIENT.value,
            ExternalResearchTerminalState.UNRESOLVED_CONFLICT.value,
        }
        and int(external.get("acquired_sources") or 0) == 1
        and observability.get("content_acquisition_state") == "content_acquired",
        "content_hash_preserved": bool(first_source.get("content_sha256"))
        and len(str(first_source.get("content_sha256"))) == 64
        and first_source.get("content_sha256") in set(observability.get("acquired_content_hashes") or ()),
        "mime_preserved": first_source.get("content_type") == "text/html",
        "claim_pipeline_connected": bool(external.get("normalized_records")) and bool(external.get("candidates")),
        "metadata_only_not_promotion_evidence": _metadata_only_payload_is_blocked(),
        "arbitrary_host_blocked": _blocked_content_state("https://evil.example/research.html") == "content_blocked",
        "unsupported_mime_blocked": _blocked_content_state("https://content.example.org/research.bin", content_type="application/octet-stream")
        == "unsupported_content_type",
        "byte_limit_blocked": _blocked_content_state("https://content.example.org/large.html", content=b"x" * (PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES + 1))
        == "content_blocked",
        "timeout_fail_closed": _blocked_content_state("https://content.example.org/timeout.html", failure=TimeoutError("timeout"))
        == "fetch_failure",
        "fixture_promotion_blocked": fixture_payload.get("fixture_promotion_blocked") is True
        and fixture_payload.get("promotion_status") == "blocked_fixture"
        and fixture_payload.get("approval_required") is False,
        "no_mutation": not payload.get("strategy_mutated")
        and not payload.get("order_executed")
        and not payload.get("broker_order_called")
        and not payload.get("kis_order_called"),
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"production safe content acquisition release check failed: {failed}")
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "content_acquisition_state": "content_acquired",
        "content_source": first_source.get("final_url"),
        "content_hash": first_source.get("content_sha256"),
        "evidence_candidates": len(_as_list(external.get("candidates"))),
        "metadata_only_evidence_blocked": True,
        "fixture_promotion_blocked": True,
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }


def production_grounded_evidence_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    evidence = [_as_dict(item) for item in _as_list(learning.get("grounded_evidence"))]
    checks = {
        "content_acquired_evidence_present": bool(evidence),
        "metadata_only_rejected": all(item.get("metadata_only") is False for item in evidence),
        "content_hash_preserved": all(len(str(item.get("content_sha256") or "")) == 64 for item in evidence),
        "source_lineage_present": bool(_as_list(_as_dict(learning.get("promotion_candidate_context")).get("source_lineage"))),
        "no_fixture_evidence": all(item.get("fixture_backed") is False for item in evidence),
    }
    _raise_if_failed("production grounded evidence", checks)
    return _release_stage_payload(payload, "grounded_evidence", checks)


def production_evidence_backed_hypothesis_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    hypotheses = [_as_dict(item) for item in _as_list(learning.get("hypotheses"))]
    checks = {
        "hypothesis_present": bool(hypotheses),
        "all_hypotheses_have_evidence": all(_as_list(item.get("evidence_ids")) for item in hypotheses),
        "metadata_only_not_used": all(item.get("metadata_only") is False for item in hypotheses),
        "fixture_not_used": all(item.get("fixture_backed") is False for item in hypotheses),
        "strategy_delta_present": all(_as_list(item.get("changed_rules")) for item in hypotheses),
    }
    _raise_if_failed("production evidence-backed hypothesis", checks)
    return _release_stage_payload(payload, "evidence_backed_hypothesis", checks)


def production_strategy_experiment_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    experiments = [_as_dict(item) for item in _as_list(learning.get("candidate_experiments"))]
    checks = {
        "experiment_present": bool(experiments),
        "candidate_backtest_executed": all(item.get("status") == "executed" for item in experiments),
        "strategy_fingerprint_matched": all(item.get("strategy_fingerprint_matched") is True for item in experiments),
        "real_dataset_used": all(str(item.get("dataset_source", "")).startswith("real:") for item in experiments),
        "no_fixture_experiment": all(item.get("fixture_backed") is False for item in experiments),
    }
    _raise_if_failed("production strategy experiment", checks)
    return _release_stage_payload(payload, "strategy_experiment", checks)


def production_authoritative_candidate_validation_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    validation = _as_dict(learning.get("authoritative_candidate_validation"))
    checks = {
        "validation_status": validation.get("status") == "validated",
        "authoritative_backtest_present": _as_dict(validation.get("checks")).get("authoritative_backtest_present") is True,
        "backtest_source_real": _as_dict(validation.get("checks")).get("backtest_source_real") is True,
        "fingerprint_matched": _as_dict(validation.get("checks")).get("candidate_strategy_fingerprint_matched") is True,
        "metrics_present": _as_dict(validation.get("checks")).get("metrics_present") is True,
    }
    _raise_if_failed("production authoritative candidate validation", checks)
    return _release_stage_payload(payload, "authoritative_candidate_validation", checks)


def production_robustness_ranking_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    ranking = _as_dict(learning.get("ranking"))
    ranked = [_as_dict(item) for item in _as_list(ranking.get("ranked"))]
    checks = {
        "ranking_status": ranking.get("status") == "ranked",
        "ranked_candidate_present": bool(ranked),
        "ranked_source_real": bool(ranked) and ranked[0].get("fixture_backed") is False,
        "ranked_metrics_present": bool(ranked) and int(ranked[0].get("trade_count") or 0) > 0,
        "ranking_not_mutating": payload.get("strategy_mutated") is False and payload.get("order_executed") is False,
    }
    _raise_if_failed("production robustness ranking", checks)
    return _release_stage_payload(payload, "robustness_ranking", checks)


def production_human_promotion_gate_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    fixture_payload = production_autonomous_learning_payload_from_baseline(
        "fixture promotion must remain blocked",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="fixture"),
        external_research=_release_content_external(),
    )
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    checks = {
        "human_gate_requested_for_real_review": payload.get("promotion_status") == "requires_human_approval"
        and payload.get("human_gate_status") == "awaiting_human_approval",
        "fixture_promotion_blocked": fixture_payload.get("promotion_status") == "blocked_fixture"
        and fixture_payload.get("approval_required") is False,
        "no_auto_promotion": payload.get("automatic_champion_promotion") is False,
        "no_strategy_mutation": payload.get("strategy_mutated") is False and payload.get("automatic_config_apply") is False,
        "no_orders": payload.get("broker_order_called") is False and payload.get("kis_order_called") is False,
        "promotion_context_present": bool(learning.get("promotion_candidate_context")),
    }
    _raise_if_failed("production human promotion gate", checks)
    return _release_stage_payload(payload, "human_promotion_gate", checks)


def production_autonomous_learning_loop_release_check() -> Mapping[str, object]:
    payload = _release_production_learning_payload_with_content()
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    loop = _as_dict(learning.get("production_loop"))
    stages = _as_dict(loop.get("stages"))
    checks = {
        "grounded_evidence": stages.get("grounded_evidence") == "pass",
        "evidence_backed_hypothesis": stages.get("evidence_backed_hypothesis") == "pass",
        "strategy_experiment": stages.get("strategy_experiment") == "pass",
        "authoritative_candidate_validation": stages.get("authoritative_candidate_validation") == "validated",
        "robustness_ranking": stages.get("robustness_ranking") == "ranked",
        "human_promotion_gate": stages.get("human_promotion_gate") == "awaiting_human_approval",
        "no_fixture_or_metadata_promotion": payload.get("fixture_backed") is False
        and payload.get("fixture_promotion_blocked") is False,
        "safety": payload.get("safety") == "pass"
        and payload.get("strategy_mutated") is False
        and payload.get("order_executed") is False,
    }
    _raise_if_failed("production autonomous learning loop", checks)
    return _release_stage_payload(payload, "production_autonomous_learning_loop", checks)


def production_real_academic_content_resolution_release_check() -> Mapping[str, object]:
    external = _release_academic_content_external()
    payload = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy academic DOI content resolution",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    observability = _as_dict(external.get("observability"))
    resolutions = [_as_dict(item) for item in _as_list(observability.get("content_resolution"))]
    first_resolution = resolutions[0] if resolutions else {}
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    blocked_doi = _academic_resolution_state(
        doi_final_url="https://blocked-publisher.example/research.html",
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    http_doi = _academic_resolution_state(
        doi_final_url="http://content.example.org/research.html",
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    unsupported = _academic_resolution_state(content_type="application/octet-stream")
    oversized = _academic_resolution_state(content=b"x" * (PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES + 1))
    timeout = _academic_resolution_state(failure=TimeoutError("timeout"))
    checks = {
        "starts_from_academic_locator": first_resolution.get("locator_kind") == "doi_url"
        and first_resolution.get("doi") == "10.1234/gaon-production-academic-content",
        "metadata_resource_resolved": first_resolution.get("resolution_status") == "metadata_resource_url"
        and first_resolution.get("final_host") == "content.example.org",
        "content_acquired": observability.get("content_acquisition_state") == "content_acquired"
        and int(external.get("acquired_sources") or 0) == 1,
        "grounded_evidence_created": len(_as_list(learning.get("grounded_evidence"))) >= 1,
        "hypothesis_and_experiment_connected": len(_as_list(learning.get("hypotheses"))) >= 1
        and len(_as_list(learning.get("candidate_experiments"))) >= 1,
        "blocked_publisher_fails_closed": blocked_doi["resolution_status"] == "content_blocked",
        "http_target_blocked": http_doi["resolution_status"] == "content_blocked",
        "unsupported_mime_blocked": unsupported["content_state"] == "unsupported_content_type",
        "oversized_content_blocked": oversized["content_state"] == "content_blocked",
        "timeout_fail_closed": timeout["content_state"] == "fetch_failure",
        "metadata_only_rejected": _metadata_only_payload_is_blocked(),
        "fixture_promotion_blocked": _fixture_academic_payload_is_blocked(),
        "fingerprint_mismatch_blocked": _fingerprint_mismatch_payload_is_blocked(),
        "no_mutation": not payload.get("strategy_mutated")
        and not payload.get("order_executed")
        and not payload.get("broker_order_called")
        and not payload.get("kis_order_called"),
    }
    _raise_if_failed("production real academic content resolution", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "discovered_locator": first_resolution.get("original_locator"),
        "locator_kind": first_resolution.get("locator_kind"),
        "resolution_status": first_resolution.get("resolution_status"),
        "resolved_host": first_resolution.get("final_host"),
        "content_acquisition_state": observability.get("content_acquisition_state"),
        "acquired_sources": external.get("acquired_sources"),
        "grounded_evidence_count": len(_as_list(learning.get("grounded_evidence"))),
        "hypothesis_count": len(_as_list(learning.get("hypotheses"))),
        "candidate_experiment_count": len(_as_list(learning.get("candidate_experiments"))),
        "promotion_status": payload.get("promotion_status"),
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }


def production_relevant_academic_discovery_release_check() -> Mapping[str, object]:
    transport = _ReleaseMetadataTransport(mode="relevant_then_irrelevant")
    with tempfile.TemporaryDirectory(prefix="gaon-production-relevant-discovery-") as tmp:
        external = _run_production_external_research(
            "Samsung breakout trend following academic relevance screening",
            symbol="005930",
            transport=transport,
            content_transport=_ReleaseContentTransport(),
            doi_resolution_transport=_ReleaseDoiResolutionTransport(),
            allowed_content_hosts=("content.example.org", "doi.org"),
            storage_root=tmp,
        )
    observability = _as_dict(external.get("observability"))
    relevance = [_as_dict(item) for item in _as_list(observability.get("academic_relevance"))]
    selected = [item for item in relevance if item.get("selected_for_content_acquisition")]
    rejected = [item for item in relevance if not item.get("selected_for_content_acquisition")]
    tuple_recovery = [item for item in rejected if "Tuple Recovery Strategy" in str(item.get("title"))]
    content_sources = [_as_dict(item) for item in _as_list(observability.get("content_sources"))]
    checks = {
        "relevant_financial_metadata_accepted": bool(selected)
        and selected[0].get("relevance_status") == "relevant",
        "irrelevant_tuple_rejected": bool(tuple_recovery)
        and tuple_recovery[0].get("relevance_status") == "wrong_domain",
        "relevance_observable": len(relevance) == 2
        and all(item.get("relevance_score") is not None for item in relevance),
        "rejected_not_fetched": all(
            source.get("discovery_result_id") != tuple_recovery[0].get("discovery_result_id")
            for source in content_sources
        ) if tuple_recovery else False,
        "grounded_evidence_from_relevant_only": int(external.get("acquired_sources") or 0) == 1
        and bool(external.get("candidates")),
        "no_mutation": not external.get("strategy_mutated")
        and not external.get("order_executed"),
    }
    _raise_if_failed("production relevant academic discovery", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "returned_results": len(relevance),
        "selected_relevant": len(selected),
        "rejected_irrelevant": len(rejected),
        "tuple_recovery_status": tuple_recovery[0].get("relevance_status") if tuple_recovery else None,
        "content_acquisition_state": observability.get("content_acquisition_state"),
        "grounded_evidence_count": len(_as_list(external.get("candidates"))),
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }


def production_safe_doi_redirect_release_check() -> Mapping[str, object]:
    positive = _academic_resolution_state(
        doi_final_url="https://content.example.org/research.html",
        doi_redirect_chain=(
            "https://doi.org/10.1234/gaon-production-metadata",
            "http://doi-proxy.example.org/temporary",
            "https://content.example.org/research.html",
        ),
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    http_final = _academic_resolution_state(
        doi_final_url="http://content.example.org/research.html",
        doi_redirect_chain=(
            "https://doi.org/10.1234/gaon-production-metadata",
            "http://content.example.org/research.html",
        ),
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    private_host = _academic_resolution_state(
        doi_final_url="https://127.0.0.1/research.html",
        allowed_content_hosts=("127.0.0.1", "doi.org"),
    )
    redirect_limit = _academic_resolution_state(
        doi_failure=HTTPError("https://doi.org/10.1234/loop", 403, "redirect limit exceeded", {}, None),
    )
    unsafe_scheme = _academic_resolution_state(
        doi_final_url="ftp://content.example.org/research.html",
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    unauthorized_host = _academic_resolution_state(
        doi_final_url="https://blocked-publisher.example/research.html",
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    credentials = _academic_resolution_state(
        doi_final_url="https://user:secret@content.example.org/research.html",
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    checks = {
        "http_intermediate_https_final_allowed": positive["resolution_status"] == "doi_resolved"
        and positive["resolved_host"] == "content.example.org"
        and positive["content_state"] == "content_acquired",
        "http_final_blocked": http_final["resolution_status"] == "content_blocked",
        "private_host_blocked": private_host["resolution_status"] == "content_blocked",
        "redirect_limit_blocked": redirect_limit["resolution_status"] == "resolution_failure",
        "unsafe_scheme_blocked": unsafe_scheme["resolution_status"] == "content_blocked",
        "unauthorized_host_blocked": unauthorized_host["resolution_status"] == "content_blocked",
        "credentials_blocked": credentials["resolution_status"] == "content_blocked",
    }
    _raise_if_failed("production safe doi redirect", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "positive_resolution_status": positive["resolution_status"],
        "positive_redirect_chain": positive["redirect_chain"],
        "http_final_blocked": True,
        "private_host_blocked": True,
        "redirect_limit_blocked": True,
        "unsafe_scheme_blocked": True,
        "unauthorized_host_blocked": True,
        "credentials_blocked": True,
        "checks": checks,
        "safety": "pass",
    }


def production_relevant_academic_content_loop_release_check() -> Mapping[str, object]:
    external = _release_academic_content_external(
        transport=_ReleaseMetadataTransport(mode="relevant_then_irrelevant"),
        doi_resolution_transport=_ReleaseDoiResolutionTransport(
            final_url="https://content.example.org/research.html",
            redirect_chain=(
                "https://doi.org/10.1234/financial-breakout-rules",
                "http://doi-proxy.example.org/temporary",
                "https://content.example.org/research.html",
            ),
        ),
        allowed_content_hosts=("content.example.org", "doi.org"),
    )
    payload = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy relevant academic content loop",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    observability = _as_dict(external.get("observability"))
    relevance = [_as_dict(item) for item in _as_list(observability.get("academic_relevance"))]
    resolutions = [_as_dict(item) for item in _as_list(observability.get("content_resolution"))]
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    checks = {
        "strategy_specific_query": any(
            "financial markets breakout trend following" in str(query)
            for query in _as_list(observability.get("generated_academic_queries"))
        ),
        "relevance_screening_selected_one": sum(
            1 for item in relevance if item.get("selected_for_content_acquisition")
        ) == 1,
        "irrelevant_rejected": any(
            item.get("relevance_status") == "wrong_domain"
            for item in relevance
        ),
        "doi_redirect_resolved": bool(resolutions)
        and resolutions[0].get("resolution_status") in {"metadata_resource_url", "doi_resolved"},
        "content_acquired": observability.get("content_acquisition_state") == "content_acquired",
        "grounded_evidence_created": len(_as_list(learning.get("grounded_evidence"))) >= 1,
        "hypothesis_created": len(_as_list(learning.get("hypotheses"))) >= 1,
        "candidate_experiment_created": len(_as_list(learning.get("candidate_experiments"))) >= 1,
        "no_mutation": not payload.get("strategy_mutated")
        and not payload.get("order_executed")
        and not payload.get("broker_order_called")
        and not payload.get("kis_order_called"),
    }
    _raise_if_failed("production relevant academic content loop", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "content_acquisition_state": observability.get("content_acquisition_state"),
        "relevance_records": len(relevance),
        "selected_relevant": sum(1 for item in relevance if item.get("selected_for_content_acquisition")),
        "grounded_evidence_count": len(_as_list(learning.get("grounded_evidence"))),
        "hypothesis_count": len(_as_list(learning.get("hypotheses"))),
        "candidate_experiment_count": len(_as_list(learning.get("candidate_experiments"))),
        "promotion_status": payload.get("promotion_status"),
        "strategy_mutated": False,
        "order_executed": False,
        "checks": checks,
        "safety": "pass",
    }


def production_academic_source_fallback_release_check() -> Mapping[str, object]:
    doi_transport = _ReleaseDoiResolutionTransport(
        failures_by_doi={
            "10.1142/9789813225107_0009": HTTPError(
                "https://doi.org/10.1142/9789813225107_0009",
                403,
                "Forbidden",
                {},
                None,
            )
        },
        final_urls_by_doi={
            "10.1007/978-3-031-90907-8_3": "https://content.example.org/trend-following-anatomy.html",
            "10.1007/978-3-031-90907-8_14": "https://content.example.org/trading-frequency.html",
        },
    )
    with tempfile.TemporaryDirectory(prefix="gaon-production-academic-fallback-") as tmp:
        external = _run_production_external_research(
            "Samsung breakout strategy resilient academic source fallback",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="fallback_after_403"),
            content_transport=_ReleaseContentTransport(),
            doi_resolution_transport=doi_transport,
            allowed_content_hosts=("content.example.org", "doi.org"),
            storage_root=tmp,
        )
    payload = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy resilient academic source fallback",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    observability = _as_dict(external.get("observability"))
    attempts = [_as_dict(item) for item in _as_list(observability.get("source_attempts"))]
    resolutions = [_as_dict(item) for item in _as_list(observability.get("content_resolution"))]
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    checks = {
        "first_source_attempted": len(resolutions) >= 1
        and resolutions[0].get("doi") == "10.1142/9789813225107_0009",
        "first_failure_recorded": len(resolutions) >= 1
        and resolutions[0].get("resolution_status") == "resolution_failure",
        "second_source_attempted": len(resolutions) >= 2
        and resolutions[1].get("doi") == "10.1007/978-3-031-90907-8_3",
        "second_content_acquired": observability.get("content_acquisition_state") == "content_acquired"
        and int(external.get("acquired_sources") or 0) == 1,
        "grounded_evidence_created": len(_as_list(learning.get("grounded_evidence"))) >= 1,
        "failed_source_observable": any(item.get("failure_kind") == "resolution_failure" for item in attempts),
        "third_not_overfetched": len(resolutions) == 2,
        "no_mutation_or_order": payload.get("strategy_mutated") is False
        and payload.get("order_executed") is False
        and payload.get("broker_order_called") is False
        and payload.get("kis_order_called") is False,
    }
    _raise_if_failed("production academic source fallback", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "state": external.get("state"),
        "relevant_result_count": observability.get("relevant_result_count"),
        "resolution_attempt_count": observability.get("resolution_attempt_count"),
        "acquisition_attempt_count": observability.get("acquisition_attempt_count"),
        "acquired_source_count": observability.get("acquired_source_count"),
        "grounded_source_count": observability.get("grounded_source_count"),
        "source_attempts": attempts,
        "promotion_status": payload.get("promotion_status"),
        "checks": checks,
        "safety": "pass",
    }


def production_academic_source_budget_release_check() -> Mapping[str, object]:
    doi_transport = _ReleaseDoiResolutionTransport(
        failures_by_doi={
            "10.1234/duplicate-breakout": HTTPError("https://doi.org/10.1234/duplicate-breakout", 403, "Forbidden", {}, None),
            "10.1234/unique-breakout": HTTPError("https://doi.org/10.1234/unique-breakout", 403, "Forbidden", {}, None),
        }
    )
    with tempfile.TemporaryDirectory(prefix="gaon-production-academic-budget-") as tmp:
        external = _run_production_external_research(
            "Samsung breakout strategy academic source budget",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="duplicate_relevant_doi"),
            content_transport=_ReleaseContentTransport(),
            doi_resolution_transport=doi_transport,
            allowed_content_hosts=("content.example.org", "doi.org"),
            storage_root=tmp,
        )
    observability = _as_dict(external.get("observability"))
    blockers = [str(item) for item in _as_list(external.get("blockers"))]
    checks = {
        "resolution_attempt_budget_respected": int(observability.get("resolution_attempt_count") or 0) <= PRODUCTION_EXTERNAL_RESOLUTION_ATTEMPTS,
        "acquisition_attempt_budget_respected": int(observability.get("acquisition_attempt_count") or 0) <= PRODUCTION_EXTERNAL_CONTENT_ACQUISITION_ATTEMPTS,
        "acquired_source_budget_respected": int(observability.get("acquired_source_count") or 0) <= PRODUCTION_EXTERNAL_MAX_ACQUIRED_SOURCES,
        "grounded_source_budget_respected": int(observability.get("grounded_source_count") or 0) <= PRODUCTION_EXTERNAL_MAX_GROUNDED_SOURCES,
        "duplicate_doi_not_retried": int(external.get("duplicate_results") or 0) >= 1
        and doi_transport.calls == 2,
        "no_unbounded_retry": doi_transport.calls <= PRODUCTION_EXTERNAL_RESOLUTION_ATTEMPTS,
    }
    _raise_if_failed("production academic source budget", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "state": external.get("state"),
        "resolution_attempt_count": observability.get("resolution_attempt_count"),
        "acquisition_attempt_count": observability.get("acquisition_attempt_count"),
        "acquired_source_count": observability.get("acquired_source_count"),
        "grounded_source_count": observability.get("grounded_source_count"),
        "duplicate_skipped": int(external.get("duplicate_results") or 0) >= 1,
        "checks": checks,
        "safety": "pass",
    }


def production_autonomous_learning_state_semantics_release_check() -> Mapping[str, object]:
    real_missing = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy missing external evidence",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=_empty_external_research("005930"),
    )
    fixture_payload = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy fixture evidence",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="fixture"),
        external_research=_release_external_ready(),
    )
    real_ready = production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy ready external evidence",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=_release_external_ready(),
    )
    missing_learning = _as_dict(real_missing.get("autonomous_learning_v2"))
    ready_learning = _as_dict(real_ready.get("autonomous_learning_v2"))
    checks = {
        "real_missing_not_blocked_fixture": real_missing.get("promotion_status") == "needs_real_validation",
        "zero_hypotheses_not_proposed": missing_learning.get("hypothesis_status") != "proposed"
        and len(_as_list(missing_learning.get("hypotheses"))) == 0,
        "fixture_blocking_unchanged": fixture_payload.get("promotion_status") == "blocked_fixture"
        and fixture_payload.get("approval_required") is False,
        "grounded_real_existing_state_preserved": ready_learning.get("hypothesis_status") == "proposed"
        and real_ready.get("promotion_status") in {"requires_human_approval", "needs_real_validation"},
        "no_mutation_or_order": all(
            payload.get("strategy_mutated") is False
            and payload.get("order_executed") is False
            and payload.get("broker_order_called") is False
            and payload.get("kis_order_called") is False
            for payload in (real_missing, fixture_payload, real_ready)
        ),
    }
    _raise_if_failed("production autonomous learning state semantics", checks)
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "real_missing_promotion_status": real_missing.get("promotion_status"),
        "real_missing_hypothesis_status": missing_learning.get("hypothesis_status"),
        "fixture_promotion_status": fixture_payload.get("promotion_status"),
        "real_ready_hypothesis_status": ready_learning.get("hypothesis_status"),
        "checks": checks,
        "safety": "pass",
    }


def _run_production_external_research(
    request_text: str,
    *,
    symbol: str,
    transport: JsonTransport | None = None,
    content_transport: HttpsBinaryTransport | None = None,
    network_enabled: bool = True,
    content_network_enabled: bool = True,
    allowed_content_hosts: tuple[str, ...] = PRODUCTION_EXTERNAL_CONTENT_ALLOWED_HOSTS,
    storage_root: str | None = None,
    doi_resolution_transport: object | None = None,
) -> Mapping[str, object]:
    storage_root = storage_root or os.environ.get("GAON_EXTERNAL_RESEARCH_STORAGE_ROOT")
    configured_content_hosts = _configured_content_hosts(allowed_content_hosts)
    storage = GaonStorage(storage_root) if storage_root else GaonStorage()
    question = ResearchQuestion(
        question_id=f"research-question:{_hash({'symbol': symbol, 'request_text': request_text})[:16]}",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question=(
            "financial markets breakout trend following trading rules "
            "moving average volume confirmation stop-loss trailing exit "
            "out-of-sample robustness evidence"
        ),
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
    content_policy = ContentAcquisitionPolicy(
        network_enabled=content_network_enabled,
        allowed_hosts=configured_content_hosts,
        allowed_content_types=PRODUCTION_EXTERNAL_ALLOWED_CONTENT_TYPES,
        max_content_bytes=PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES,
        timeout_seconds=PRODUCTION_EXTERNAL_CONTENT_TIMEOUT_SECONDS,
    )
    result = AutonomousExternalResearchExecutor(
        planner=SourceDiscoveryPlanner(
            budget=DiscoveryBudget(
                max_queries=PRODUCTION_EXTERNAL_DISCOVERY_MAX_PROVIDER_CALLS,
                max_results_per_query=PRODUCTION_EXTERNAL_DISCOVERY_MAX_CANDIDATE_RESULTS,
                max_total_results=PRODUCTION_EXTERNAL_DISCOVERY_MAX_CANDIDATE_RESULTS,
            )
        ),
        discovery_executor=discovery_executor,
        ingestion=DiscoveryEvidenceIngestor(storage),
        acquirer=BoundedSourceContentAcquirer(
            storage,
            policy=content_policy,
            transport=content_transport,
        ),
        resolver=AcademicContentResolver(policy=content_policy, doi_transport=doi_resolution_transport),  # type: ignore[arg-type]
        policy=ExternalResearchExecutionPolicy(
            max_iterations=1,
            max_provider_calls=PRODUCTION_EXTERNAL_DISCOVERY_MAX_PROVIDER_CALLS,
            max_sources=PRODUCTION_EXTERNAL_MAX_ACQUIRED_SOURCES,
            max_relevant_candidates=PRODUCTION_EXTERNAL_RELEVANT_CANDIDATES,
            max_resolution_attempts=PRODUCTION_EXTERNAL_RESOLUTION_ATTEMPTS,
            max_content_acquisition_attempts=PRODUCTION_EXTERNAL_CONTENT_ACQUISITION_ATTEMPTS,
            max_acquired_sources=PRODUCTION_EXTERNAL_MAX_ACQUIRED_SOURCES,
            max_grounded_sources=PRODUCTION_EXTERNAL_MAX_GROUNDED_SOURCES,
            max_total_download_bytes=PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES,
            content_network_enabled=content_network_enabled,
            allowed_content_hosts=configured_content_hosts,
        )
    ).run(question)
    payload = result.to_json()
    if _network_disabled_discovery(payload):
        payload["state"] = "discovery_network_disabled"
        payload["blockers"] = list(_as_list(payload.get("blockers"))) + ["discovery_network_disabled"]
    payload["observability"] = _external_research_observability(
        payload,
        network_policy=network_policy,
        allowed_content_hosts=configured_content_hosts,
        content_network_enabled=content_network_enabled,
    )
    return payload


def _external_research_observability(
    payload: Mapping[str, object],
    *,
    network_policy: NetworkExecutionPolicy,
    allowed_content_hosts: tuple[str, ...],
    content_network_enabled: bool,
) -> dict[str, object]:
    discovery = _as_dict(payload.get("discovery_run"))
    records = [_as_dict(item) for item in _as_list(discovery.get("query_records"))]
    results = [_as_dict(item) for item in _as_list(discovery.get("results"))]
    failure_kinds = [str(item.get("failure_kind")) for item in records if item.get("failure_kind")]
    blockers = [str(item) for item in _as_list(payload.get("blockers"))]
    content_blockers = [
        item
        for item in blockers
        if item.startswith((
            "content_unavailable",
            "content_blocked",
            "unsupported_content_type",
            "fetch_failure",
            "resolution_failure",
            "resolution_budget_exhausted",
            "acquisition_budget_exhausted",
            "acquired_source_budget_exhausted",
        ))
    ]
    relevance_blockers = [
        item
        for item in blockers
        if item.startswith(("insufficient_relevance", "wrong_domain", "insufficient_metadata"))
    ]
    acquisitions = [_as_dict(item) for item in _as_list(payload.get("acquisition_records"))]
    relevance = [_as_dict(item) for item in _as_list(payload.get("relevance_records"))]
    resolutions = [_as_dict(item) for item in _as_list(payload.get("resolution_records"))]
    normalized_records = [_as_dict(item) for item in _as_list(payload.get("normalized_records"))]
    acquired = [item for item in acquisitions if item.get("status") == "acquired"]
    failed = [item for item in acquisitions if item.get("status") != "acquired"]
    source_attempts = _source_attempts(relevance, resolutions, acquisitions)
    grounded_source_count = len(
        {
            str(item.get("source_id"))
            for item in _as_list(payload.get("candidates"))
            if _as_dict(item).get("source_id")
        }
    )
    if acquired and payload.get("candidates"):
        content_state = "content_acquired"
    elif acquired:
        content_state = "content_acquired_no_claims"
    elif any(item.startswith("unsupported_content_type") for item in content_blockers):
        content_state = "unsupported_content_type"
    elif any(item.startswith("content_blocked") for item in content_blockers):
        content_state = "content_blocked"
    elif any(item.startswith("fetch_failure") for item in content_blockers):
        content_state = "fetch_failure"
    elif any(item.startswith("resolution_failure") for item in content_blockers):
        content_state = "resolution_failure"
    elif content_blockers:
        content_state = "metadata_only"
    elif relevance_blockers and not any(item.get("selected_for_content_acquisition") for item in relevance):
        content_state = "academic_results_irrelevant"
    else:
        content_state = "not_attempted"
    if not bool(discovery.get("network_enabled", network_policy.network_enabled)):
        terminal_state = "discovery_network_disabled"
    elif failure_kinds and not results:
        terminal_state = "provider_failure"
    elif relevance_blockers and not any(item.get("selected_for_content_acquisition") for item in relevance):
        terminal_state = "no_relevant_research_path"
    elif content_blockers and not payload.get("candidates"):
        terminal_state = content_state
    else:
        terminal_state = str(payload.get("state") or "unknown")
    return {
        "network_enabled": bool(discovery.get("network_enabled", network_policy.network_enabled)),
        "network_executed": bool(payload.get("network_executed") or discovery.get("network_executed")),
        "provider_calls": int(payload.get("provider_calls") or discovery.get("provider_calls") or 0),
        "allowed_api_hosts": list(network_policy.allowed_api_hosts),
        "timeout_seconds": network_policy.timeout_seconds,
        "max_response_bytes": network_policy.max_response_bytes,
        "content_network_enabled": content_network_enabled,
        "allowed_content_hosts": list(allowed_content_hosts),
        "content_timeout_seconds": PRODUCTION_EXTERNAL_CONTENT_TIMEOUT_SECONDS,
        "max_content_bytes": PRODUCTION_EXTERNAL_CONTENT_MAX_BYTES,
        "max_relevant_candidates": PRODUCTION_EXTERNAL_RELEVANT_CANDIDATES,
        "max_resolution_attempts": PRODUCTION_EXTERNAL_RESOLUTION_ATTEMPTS,
        "max_content_acquisition_attempts": PRODUCTION_EXTERNAL_CONTENT_ACQUISITION_ATTEMPTS,
        "max_acquired_sources": PRODUCTION_EXTERNAL_MAX_ACQUIRED_SOURCES,
        "max_grounded_sources": PRODUCTION_EXTERNAL_MAX_GROUNDED_SOURCES,
        "query_records": [
            {
                "query": item.get("query"),
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
        "generated_academic_queries": [
            item.get("query")
            for item in records
            if item.get("query")
        ],
        "academic_relevance": [
            {
                "discovery_result_id": item.get("discovery_result_id"),
                "provider": item.get("provider"),
                "title": item.get("title"),
                "doi": item.get("doi"),
                "relevance_status": item.get("relevance_status"),
                "relevance_score": item.get("relevance_score"),
                "matched_research_terms": item.get("matched_research_terms"),
                "matched_domain_terms": item.get("matched_domain_terms"),
                "matched_negative_terms": item.get("matched_negative_terms"),
                "rejected_reason": item.get("rejected_reason"),
                "selected_for_content_acquisition": item.get("selected_for_content_acquisition"),
            }
            for item in relevance
        ],
        "metadata_only": bool(results and not payload.get("normalized_records") and not payload.get("candidates")),
        "content_acquisition_state": content_state,
        "content_sources": [
            {
                "discovery_result_id": item.get("discovery_result_id"),
                "source_locator": item.get("source_locator"),
                "content_url": item.get("content_url"),
                "final_url": item.get("final_url"),
                "content_type": item.get("content_type"),
                "byte_count": item.get("byte_count"),
                "content_sha256": item.get("content_sha256"),
                "source_id": item.get("source_id"),
                "status": item.get("status"),
                "failure_kind": item.get("failure_kind"),
            }
            for item in acquisitions
        ],
        "content_resolution": [
            {
                "discovery_result_id": item.get("discovery_result_id"),
                "provider": item.get("provider"),
                "title": item.get("title"),
                "original_locator": item.get("original_locator"),
                "locator_kind": item.get("locator_kind"),
                "doi": item.get("doi"),
                "resolution_attempted": item.get("resolution_attempted"),
                "resolution_status": item.get("resolution_status"),
                "resolved_content_url": item.get("resolved_content_url"),
                "final_url": item.get("final_url"),
                "final_host": item.get("final_host"),
                "redirect_chain": item.get("redirect_chain"),
                "failure_kind": item.get("failure_kind"),
                "error_message": item.get("error_message"),
            }
            for item in resolutions
        ],
        "resolution_statuses": [item.get("resolution_status") for item in resolutions if item.get("resolution_status")],
        "discovered_result_count": len(results),
        "relevant_result_count": sum(1 for item in relevance if item.get("relevance_status") == "relevant"),
        "resolution_attempt_count": len(resolutions),
        "acquisition_attempt_count": len(acquisitions),
        "acquired_source_count": len(acquired),
        "grounded_source_count": grounded_source_count,
        "exhausted_source_candidates": any(
            str(item).startswith(("resolution_budget_exhausted", "acquisition_budget_exhausted", "acquired_source_budget_exhausted"))
            for item in blockers
        ),
        "source_attempts": source_attempts,
        "acquired_content_hashes": [item.get("content_sha256") for item in acquired if item.get("content_sha256")],
        "normalized_source_ids": [item.get("source_id") for item in normalized_records if item.get("source_id")],
        "blocked_reasons": content_blockers
        + relevance_blockers
        + [str(item.get("failure_kind")) for item in failed if item.get("failure_kind")],
        "failure_kind": failure_kinds[0] if failure_kinds else None,
        "terminal_state": terminal_state,
    }


def _configured_content_hosts(default_hosts: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get("GAON_EXTERNAL_RESEARCH_CONTENT_ALLOWED_HOSTS")
    if not raw:
        return default_hosts
    hosts = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    return hosts or default_hosts


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


def _grounded_evidence_records(external_research: Mapping[str, object]) -> list[dict[str, object]]:
    provided = [
        _as_dict(item)
        for item in _as_list(external_research.get("grounded_evidence"))
        if _as_dict(item).get("grounded") is True
    ]
    if provided:
        return provided

    acquisitions = {
        str(item.get("source_id")): item
        for item in (_as_dict(row) for row in _as_list(external_research.get("acquisition_records")))
        if item.get("status") == "acquired" and item.get("source_id") and item.get("content_sha256")
    }
    acquired_list = list(acquisitions.values())
    normalized = {
        str(item.get("source_id")): item
        for item in (_as_dict(row) for row in _as_list(external_research.get("normalized_records")))
        if item.get("status") == "normalized" and item.get("source_id") and item.get("raw_content_sha256")
    }
    normalized_list = list(normalized.values())
    discovery = _as_dict(external_research.get("discovery_run"))
    discovery_results = {
        str(item.get("result_id")): item
        for item in (_as_dict(row) for row in _as_list(discovery.get("results")))
        if item.get("result_id")
    }
    records: list[dict[str, object]] = []
    for index, row in enumerate(_as_list(external_research.get("candidates")), start=1):
        candidate = _as_dict(row)
        source_id = str(candidate.get("source_id") or "")
        acquisition = acquisitions.get(source_id) or (acquired_list[0] if len(acquired_list) == 1 else None)
        normalized_record = normalized.get(source_id) or (normalized_list[0] if len(normalized_list) == 1 else None)
        claim_text = str(candidate.get("claim_text") or "").strip()
        claim_id = str(candidate.get("claim_id") or candidate.get("candidate_id") or "")
        if not acquisition or not normalized_record or not claim_text or not claim_id:
            continue
        if acquisition.get("content_sha256") != normalized_record.get("raw_content_sha256"):
            continue
        discovery_result_id = str(acquisition.get("discovery_result_id") or normalized_record.get("discovery_result_id") or "")
        discovery_result = discovery_results.get(discovery_result_id, {})
        records.append(
            {
                "evidence_id": f"grounded-evidence:{_hash({'claim_id': claim_id, 'source_id': source_id, 'hash': acquisition.get('content_sha256')})}",
                "claim_id": claim_id,
                "claim_candidate_id": candidate.get("candidate_id"),
                "source_id": source_id,
                "discovery_result_id": discovery_result_id,
                "title": discovery_result.get("title"),
                "doi": discovery_result.get("doi"),
                "source_locator": acquisition.get("source_locator") or discovery_result.get("locator"),
                "content_url": acquisition.get("content_url"),
                "final_url": acquisition.get("final_url"),
                "content_type": acquisition.get("content_type"),
                "content_sha256": acquisition.get("content_sha256"),
                "normalized_source_id": normalized_record.get("source_id"),
                "normalized_text_sha256": normalized_record.get("normalized_text_sha256"),
                "retrieval_timestamp": acquisition.get("retrieved_at") or acquisition.get("created_at"),
                "verbatim_excerpt": claim_text,
                "source_span": {"type": "normalized_claim_sentence", "ordinal": index},
                "extraction_method": "safe_content_normalized_claim_bridge",
                "metadata_only": False,
                "fixture_backed": False,
                "grounded": True,
                "knowledge_validated": False,
                "production_approved": False,
                "strategy_mutated": False,
                "order_executed": False,
            }
        )
    return records


def _evidence_backed_hypotheses(
    grounded_evidence: list[dict[str, object]],
    *,
    baseline_strategy: Mapping[str, object],
    candidate: Mapping[str, object],
    symbol: str,
) -> list[dict[str, object]]:
    if not grounded_evidence or not candidate:
        return []
    candidate_strategy = _as_dict(candidate.get("strategy"))
    changed_rules = tuple(str(item) for item in _as_list(candidate.get("changed_fields")) if str(item))
    if not changed_rules:
        return []
    hypotheses: list[dict[str, object]] = []
    for evidence in grounded_evidence[:PRODUCTION_AUTONOMOUS_LEARNING_MAX_HYPOTHESES]:
        claim_text = str(evidence.get("verbatim_excerpt") or "")
        if not claim_text:
            continue
        hypotheses.append(
            {
                "hypothesis_id": f"strategy-hypothesis:{_hash({'symbol': symbol, 'claim_id': evidence.get('claim_id'), 'candidate': candidate_strategy.get('fingerprint'), 'changed_rules': changed_rules})}",
                "status": "evidence_backed",
                "symbol": symbol,
                "topic_key": "strategy.breakout.robustness",
                "baseline_strategy_id": baseline_strategy.get("spec_id"),
                "baseline_strategy_fingerprint": baseline_strategy.get("fingerprint"),
                "candidate_strategy_fingerprint": candidate_strategy.get("fingerprint"),
                "changed_rules": list(changed_rules),
                "evidence_ids": [evidence.get("evidence_id")],
                "claim_ids": [evidence.get("claim_id")],
                "source_ids": [evidence.get("source_id")],
                "rationale": claim_text,
                "metadata_only": False,
                "fixture_backed": False,
                "strategy_mutated": False,
                "order_executed": False,
            }
        )
    return hypotheses


def _candidate_experiment_records(
    hypotheses: list[dict[str, object]],
    *,
    experiment: StrategyResearchExperiment,
    candidate: Mapping[str, object],
    candidate_backtest: Mapping[str, object],
    metadata: Mapping[str, object],
) -> list[dict[str, object]]:
    candidate_strategy = _as_dict(candidate.get("strategy"))
    backtest_strategy = _as_dict(candidate_backtest.get("strategy"))
    records: list[dict[str, object]] = []
    for hypothesis in hypotheses[:PRODUCTION_AUTONOMOUS_LEARNING_MAX_EXPERIMENTS]:
        records.append(
            {
                "experiment_id": experiment.experiment_id,
                "hypothesis_id": hypothesis.get("hypothesis_id"),
                "status": "executed" if candidate_backtest else "needs_implementation",
                "symbol": tuple(experiment.universe_symbols),
                "start": experiment.start,
                "end": experiment.end,
                "changed_rules": list(experiment.changed_rules),
                "baseline_strategy_fingerprint": experiment.baseline_strategy_fingerprint,
                "candidate_strategy_fingerprint": candidate_strategy.get("fingerprint"),
                "backtest_strategy_fingerprint": backtest_strategy.get("fingerprint"),
                "candidate_backtest_result_id": candidate_backtest.get("result_id"),
                "strategy_fingerprint_matched": bool(
                    candidate_strategy.get("fingerprint")
                    and candidate_strategy.get("fingerprint") == backtest_strategy.get("fingerprint")
                ),
                "dataset_source": metadata.get("source"),
                "fixture_backed": bool(metadata.get("fixture_backed") or candidate_backtest.get("source") != "real"),
                "evidence_ids": list(_as_list(hypothesis.get("evidence_ids"))),
                "strategy_mutated": False,
                "order_executed": False,
            }
        )
    return records


def _authoritative_candidate_validation(
    *,
    experiment: StrategyResearchExperiment,
    evidence: AuthoritativeValidationEvidence | None,
    validation: Mapping[str, object],
    candidate: Mapping[str, object],
    candidate_backtest: Mapping[str, object],
) -> dict[str, object]:
    candidate_strategy = _as_dict(candidate.get("strategy"))
    backtest_strategy = _as_dict(candidate_backtest.get("strategy"))
    metrics = _as_dict(candidate_backtest.get("metrics"))
    checks = {
        "authoritative_backtest_present": evidence is not None and bool(candidate_backtest),
        "backtest_source_real": candidate_backtest.get("source") == "real",
        "fixture_backed_false": bool(evidence and not evidence.fixture_backed),
        "candidate_strategy_fingerprint_matched": bool(
            candidate_strategy.get("fingerprint")
            and candidate_strategy.get("fingerprint") == backtest_strategy.get("fingerprint")
        ),
        "experiment_evidence_matched": bool(evidence and evidence.experiment_id == experiment.experiment_id),
        "metrics_present": bool(metrics),
        "validation_accepted": validation.get("status") == "accepted_for_review",
    }
    blockers = [name for name, ok in checks.items() if not ok]
    return {
        "status": "validated" if not blockers else "blocked",
        "experiment_id": experiment.experiment_id,
        "backtest_result_id": candidate_backtest.get("result_id"),
        "evidence_id": evidence.evidence_id if evidence else None,
        "source": evidence.source if evidence else candidate_backtest.get("source"),
        "fixture_backed": bool(evidence.fixture_backed) if evidence else True,
        "quality_status": evidence.quality_status if evidence else "missing",
        "blocking_findings": list(evidence.blocking_findings) if evidence else ["missing_authoritative_candidate_backtest"],
        "metrics": metrics,
        "checks": checks,
        "blockers": blockers,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _production_loop_blockers(
    *,
    grounded_evidence: list[dict[str, object]],
    hypotheses: list[dict[str, object]],
    candidate_experiments: list[dict[str, object]],
    authoritative_validation: Mapping[str, object],
    ranking: Mapping[str, object],
) -> list[str]:
    blockers: list[str] = []
    if not grounded_evidence:
        blockers.append("grounded_evidence_unavailable")
    if not hypotheses:
        blockers.append("evidence_backed_hypothesis_unavailable")
    if not candidate_experiments:
        blockers.append("candidate_experiment_unavailable")
    if authoritative_validation.get("status") != "validated":
        blockers.append("authoritative_candidate_validation_unavailable")
    if ranking.get("status") != "ranked":
        blockers.append("robustness_ranking_unavailable")
    return blockers


def _production_loop_summary(
    *,
    grounded_evidence: list[dict[str, object]],
    hypotheses: list[dict[str, object]],
    candidate_experiments: list[dict[str, object]],
    authoritative_validation: Mapping[str, object],
    ranking: Mapping[str, object],
    promotion_status: str,
    human_gate_status: str,
    blockers: list[str],
) -> dict[str, object]:
    return {
        "stages": {
            "grounded_evidence": "pass" if grounded_evidence else "blocked",
            "evidence_backed_hypothesis": "pass" if hypotheses else "blocked",
            "strategy_experiment": "pass" if candidate_experiments else "blocked",
            "authoritative_candidate_validation": authoritative_validation.get("status", "blocked"),
            "robustness_ranking": ranking.get("status", "blocked"),
            "human_promotion_gate": human_gate_status,
        },
        "grounded_evidence_count": len(grounded_evidence),
        "hypothesis_count": len(hypotheses),
        "candidate_experiment_count": len(candidate_experiments),
        "promotion_status": promotion_status,
        "human_gate_status": human_gate_status,
        "blockers": list(blockers),
        "strategy_mutated": False,
        "order_executed": False,
        "safety": "pass",
    }


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
    grounded_evidence: list[dict[str, object]],
    hypotheses: list[dict[str, object]],
    candidate_experiments: list[dict[str, object]],
    authoritative_candidate_validation: Mapping[str, object],
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
        "grounded_evidence": grounded_evidence,
        "hypotheses": hypotheses,
        "candidate_experiments": candidate_experiments,
        "experiment": experiment.to_json(),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": _hash(experiment.to_json()),
        "assumptions_fingerprint": experiment.assumptions_fingerprint,
        "authoritative_validation_evidence": evidence.to_json() if evidence else None,
        "authoritative_backtest_result_id": evidence.backtest_result_id if evidence else None,
        "authoritative_candidate_validation": dict(authoritative_candidate_validation),
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
    acquisitions_by_result = {
        str(item.get("discovery_result_id")): item
        for item in (_as_dict(row) for row in _as_list(external_research.get("acquisition_records")))
        if item.get("discovery_result_id")
    }
    claims_by_source: dict[str, list[str]] = {}
    for candidate in (_as_dict(row) for row in _as_list(external_research.get("candidates"))):
        source_id = str(candidate.get("source_id") or "")
        claim_id = str(candidate.get("claim_id") or candidate.get("candidate_id") or "")
        if source_id and claim_id:
            claims_by_source.setdefault(source_id, []).append(claim_id)
    lineage: list[dict[str, object]] = []
    for result in results:
        row = _as_dict(result)
        if not row:
            continue
        acquisition = acquisitions_by_result.get(str(row.get("result_id"))) or {}
        source_id = str(acquisition.get("source_id") or "")
        content_acquired = acquisition.get("status") == "acquired"
        lineage.append(
            {
                "title": row.get("title"),
                "source_type": row.get("source_type"),
                "locator": row.get("locator"),
                "source_ids": (source_id,) if source_id else (),
                "claim_ids": tuple(claims_by_source.get(source_id, ())),
                "metadata_only": not content_acquired,
                "content_acquired": content_acquired,
                "content_type": acquisition.get("content_type"),
                "content_sha256": acquisition.get("content_sha256"),
                "acquisition_state": acquisition.get("status") or "metadata_only",
            }
        )
    return lineage


def _has_fixture_blocker(blockers: list[str]) -> bool:
    return any(
        item in {"baseline_fixture_backed", "candidate_fixture_or_fingerprint_mismatch"}
        or item.startswith("fixture_")
        for item in blockers
    )


def _source_attempts(
    relevance: list[dict[str, object]],
    resolutions: list[dict[str, object]],
    acquisitions: list[dict[str, object]],
) -> list[dict[str, object]]:
    resolution_by_result = {
        str(item.get("discovery_result_id")): item
        for item in resolutions
        if item.get("discovery_result_id")
    }
    acquisition_by_result = {
        str(item.get("discovery_result_id")): item
        for item in acquisitions
        if item.get("discovery_result_id")
    }
    attempts: list[dict[str, object]] = []
    relevant_rank = 0
    for item in relevance:
        if item.get("relevance_status") == "relevant":
            relevant_rank += 1
        result_id = str(item.get("discovery_result_id") or "")
        resolution = resolution_by_result.get(result_id, {})
        acquisition = acquisition_by_result.get(result_id, {})
        failure_kind = (
            acquisition.get("failure_kind")
            or resolution.get("failure_kind")
            or item.get("rejected_reason")
        )
        evidence_count = 1 if acquisition.get("status") == "acquired" else 0
        attempts.append(
            {
                "rank": relevant_rank if item.get("relevance_status") == "relevant" else None,
                "title": item.get("title"),
                "doi": item.get("doi"),
                "relevance_score": item.get("relevance_score"),
                "relevance_status": item.get("relevance_status"),
                "resolution_status": resolution.get("resolution_status"),
                "acquisition_status": acquisition.get("status"),
                "failure_kind": failure_kind,
                "evidence_count": evidence_count,
            }
        )
    return attempts


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
        if self.mode == "irrelevant_tuple":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1007/978-3-322-93860-2_11",
                            "title": ["The Location and Replication Independent Tuple Recovery Strategy"],
                            "type": "book-chapter",
                            "abstract": (
                                "A distributed systems tuple recovery and data replication "
                                "strategy for software architecture."
                            ),
                            "URL": "https://doi.org/10.1007/978-3-322-93860-2_11",
                        }
                    ]
                }
            }
        if self.mode == "relevant_then_irrelevant":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1234/financial-breakout-rules",
                            "title": ["Financial market breakout trading rules with moving average filters"],
                            "type": "journal-article",
                            "abstract": (
                                "Empirical evidence on technical trading rules, "
                                "trend following, volume confirmation, and out-of-sample robustness."
                            ),
                            "URL": "https://doi.org/10.1234/financial-breakout-rules",
                        },
                        {
                            "DOI": "10.1007/978-3-322-93860-2_11",
                            "title": ["The Location and Replication Independent Tuple Recovery Strategy"],
                            "type": "book-chapter",
                            "abstract": "Distributed systems tuple recovery and replication.",
                            "URL": "https://doi.org/10.1007/978-3-322-93860-2_11",
                        },
                    ]
                }
            }
        if self.mode == "fallback_after_403":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1142/9789813225107_0009",
                            "title": ["Building a Breakout Trend-Following Trading System using Regression Methods"],
                            "type": "book-chapter",
                            "abstract": (
                                "Financial markets breakout trend following trading system "
                                "with moving average and volume confirmation robustness evidence "
                                "for securities investment portfolio returns and price momentum."
                            ),
                            "URL": "https://doi.org/10.1142/9789813225107_0009",
                        },
                        {
                            "DOI": "10.1007/978-3-031-90907-8_3",
                            "title": ["Trend-Following Trading Rules and Their Anatomy"],
                            "type": "book-chapter",
                            "abstract": (
                                "Equity market trend following technical trading rules, "
                                "moving average filters, stop-loss controls, and out-of-sample robustness."
                            ),
                            "URL": "https://doi.org/10.1007/978-3-031-90907-8_3",
                        },
                        {
                            "DOI": "10.1007/978-3-031-90907-8_14",
                            "title": ["Optimal Trading Frequency for Trend-Following Strategies"],
                            "type": "book-chapter",
                            "abstract": (
                                "Financial markets trading frequency for trend following strategies "
                                "with transaction cost and robustness evidence."
                            ),
                            "URL": "https://doi.org/10.1007/978-3-031-90907-8_14",
                        },
                        {
                            "DOI": "10.1007/978-3-322-93860-2_11",
                            "title": ["The Location and Replication Independent Tuple Recovery Strategy"],
                            "type": "book-chapter",
                            "abstract": "Distributed systems tuple recovery and data replication strategy.",
                            "URL": "https://doi.org/10.1007/978-3-322-93860-2_11",
                        },
                        {
                            "DOI": "10.9999/unrelated",
                            "title": ["A non-financial strategy note"],
                            "type": "journal-article",
                            "abstract": "General software architecture strategy.",
                            "URL": "https://doi.org/10.9999/unrelated",
                        },
                    ]
                }
            }
        if self.mode == "duplicate_relevant_doi":
            item = {
                "DOI": "10.1234/duplicate-breakout",
                "title": ["Financial market breakout trading rules duplicate"],
                "type": "journal-article",
                "abstract": (
                    "Equity market breakout trend following moving average trading rules "
                    "and out-of-sample robustness."
                ),
                "URL": "https://doi.org/10.1234/duplicate-breakout",
            }
            return {"message": {"items": [item, dict(item), {**item, "DOI": "10.1234/unique-breakout", "URL": "https://doi.org/10.1234/unique-breakout"}]}}
        if self.mode == "direct_content":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "",
                            "title": ["Financial market breakout trading rule robustness"],
                            "type": "journal-article",
                            "abstract": (
                                "This study evaluates breakout and moving average "
                                "technical trading rules in equity markets."
                            ),
                            "URL": "https://content.example.org/research.html",
                        }
                    ]
                }
            }
        if self.mode == "doi_with_resource":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1234/gaon-production-academic-content",
                            "title": ["Financial market breakout trading rule academic content"],
                            "type": "journal-article",
                            "abstract": (
                                "Evidence on trend following, volume confirmation, "
                                "and out-of-sample robustness in equity trading."
                            ),
                            "URL": "https://doi.org/10.1234/gaon-production-academic-content",
                            "link": [
                                {
                                    "URL": "https://content.example.org/research.html",
                                    "content-type": "text/html",
                                }
                            ],
                        }
                    ]
                }
            }
        return {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/gaon-production-metadata",
                        "title": ["Financial market breakout trading rule metadata"],
                        "type": "journal-article",
                        "abstract": (
                            "Metadata-only record about technical trading rules, "
                            "trend following, and equity market robustness."
                        ),
                        "URL": "https://doi.org/10.1234/gaon-production-metadata",
                    }
                ]
            }
        }


class _ReleaseContentTransport:
    def __init__(
        self,
        *,
        content_type: str = "text/html",
        content: bytes = (
            b"<html><body>Claim: breakout filters can reduce false signals. "
            b"Claim: independent validation should be required before promotion.</body></html>"
        ),
        failure: BaseException | None = None,
    ) -> None:
        self.content_type = content_type
        self.content = content
        self.failure = failure
        self.calls = 0

    def fetch(self, target, *, policy):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return FetchPayload(
            final_url=target.content_url,
            content_type=self.content_type,
            content=self.content,
        )


class _ReleaseDoiResolutionTransport:
    def __init__(
        self,
        *,
        final_url: str = "https://content.example.org/research.html",
        redirect_chain: tuple[str, ...] | None = None,
        failure: BaseException | None = None,
        failures_by_doi: Mapping[str, BaseException] | None = None,
        final_urls_by_doi: Mapping[str, str] | None = None,
    ) -> None:
        self.final_url = final_url
        self.redirect_chain = redirect_chain
        self.failure = failure
        self.failures_by_doi = dict(failures_by_doi or {})
        self.final_urls_by_doi = dict(final_urls_by_doi or {})
        self.calls = 0
        self.urls: list[str] = []

    def resolve(self, url: str, *, policy: ContentAcquisitionPolicy):  # type: ignore[no-untyped-def]
        from gaon.knowledge.external_research_execution import ContentResolutionPayload

        self.calls += 1
        self.urls.append(url)
        if self.failure is not None:
            raise self.failure
        for doi, failure in self.failures_by_doi.items():
            if doi in url:
                raise failure
        final_url = self.final_url
        for doi, configured_url in self.final_urls_by_doi.items():
            if doi in url:
                final_url = configured_url
                break
        chain = self.redirect_chain or (url, final_url)
        return ContentResolutionPayload(final_url=final_url, redirect_chain=chain)


def _metadata_only_payload_is_blocked() -> bool:
    with tempfile.TemporaryDirectory(prefix="gaon-production-safe-content-metadata-") as tmp:
        external = _run_production_external_research(
            "metadata only external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            content_network_enabled=False,
            storage_root=tmp,
        )
    payload = production_autonomous_learning_payload_from_baseline(
        "metadata only external research",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=external,
    )
    return (
        external.get("state") == ExternalResearchTerminalState.CONTENT_UNAVAILABLE.value
        and not external.get("candidates")
        and payload.get("approval_required") is False
        and payload.get("promotion_status") == "needs_real_validation"
    )


def _blocked_content_state(
    content_url: str,
    *,
    content_type: str = "text/html",
    content: bytes = b"<html><body>Claim: safe content.</body></html>",
    failure: BaseException | None = None,
) -> str:
    mode = "direct_content"
    with tempfile.TemporaryDirectory(prefix="gaon-production-safe-content-blocked-") as tmp:
        external = _run_production_external_research(
            "blocked content external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode=mode),
            content_transport=_ReleaseContentTransport(content_type=content_type, content=content, failure=failure),
            allowed_content_hosts=("content.example.org",),
            storage_root=tmp,
        )
    # The direct-content fixture always returns content.example.org; override by
    # invoking the execution stack through a one-off resolver would be larger
    # than needed. Reclassify host blocking directly through the acquisition
    # policy by using a targeted synthetic transport URL when requested.
    if "evil.example" in content_url:
        with tempfile.TemporaryDirectory(prefix="gaon-production-safe-content-host-") as tmp:
            external = _run_production_external_research(
                "blocked host external research",
                symbol="005930",
                transport=_ReleaseMetadataTransport(mode="direct_content"),
                content_transport=_ReleaseContentTransport(),
                allowed_content_hosts=("other.example.org",),
                storage_root=tmp,
            )
    return str(_as_dict(external.get("observability")).get("content_acquisition_state"))


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
        "grounded_evidence": [
            {
                "evidence_id": "grounded-evidence:release-1854",
                "claim_id": "claim:release-1854",
                "source_id": "source:release-1854",
                "source_locator": "https://doi.org/10.0000/strategylab-release-1854",
                "content_type": "text/html",
                "content_sha256": "0" * 64,
                "verbatim_excerpt": "Breakout filters can reduce false signals.",
                "metadata_only": False,
                "fixture_backed": False,
                "grounded": True,
            }
        ],
        "blockers": [],
        "network_executed": False,
    }


def _release_content_external() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gaon-production-loop-release-") as tmp:
        return dict(
            _run_production_external_research(
                "Samsung breakout strategy external evidence safe content acquisition",
                symbol="005930",
                transport=_ReleaseMetadataTransport(mode="direct_content"),
                content_transport=_ReleaseContentTransport(),
                allowed_content_hosts=("content.example.org",),
                storage_root=tmp,
            )
        )


def _release_academic_content_external(
    *,
    transport: _ReleaseMetadataTransport | None = None,
    content_transport: _ReleaseContentTransport | None = None,
    doi_resolution_transport: _ReleaseDoiResolutionTransport | None = None,
    allowed_content_hosts: tuple[str, ...] = ("content.example.org", "doi.org"),
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gaon-production-academic-resolution-") as tmp:
        return dict(
            _run_production_external_research(
                "Samsung breakout strategy academic DOI content resolution",
                symbol="005930",
                transport=transport or _ReleaseMetadataTransport(mode="doi_with_resource"),
                content_transport=content_transport or _ReleaseContentTransport(),
                doi_resolution_transport=doi_resolution_transport,
                allowed_content_hosts=allowed_content_hosts,
                storage_root=tmp,
            )
        )


def _academic_resolution_state(
    *,
    doi_final_url: str = "https://content.example.org/research.html",
    doi_redirect_chain: tuple[str, ...] | None = None,
    allowed_content_hosts: tuple[str, ...] = ("content.example.org", "doi.org"),
    content_type: str = "text/html",
    content: bytes = b"<html><body>Claim: breakout filters can reduce false signals.</body></html>",
    failure: BaseException | None = None,
    doi_failure: BaseException | None = None,
) -> dict[str, object]:
    external = _release_academic_content_external(
        transport=_ReleaseMetadataTransport(),
        content_transport=_ReleaseContentTransport(content_type=content_type, content=content, failure=failure),
        doi_resolution_transport=_ReleaseDoiResolutionTransport(final_url=doi_final_url, redirect_chain=doi_redirect_chain, failure=doi_failure),
        allowed_content_hosts=allowed_content_hosts,
    )
    observability = _as_dict(external.get("observability"))
    resolutions = [_as_dict(item) for item in _as_list(observability.get("content_resolution"))]
    first_resolution = resolutions[0] if resolutions else {}
    return {
        "resolution_status": first_resolution.get("resolution_status"),
        "resolved_host": first_resolution.get("final_host"),
        "redirect_chain": first_resolution.get("redirect_chain"),
        "content_state": observability.get("content_acquisition_state"),
        "state": external.get("state"),
        "blockers": list(_as_list(external.get("blockers"))),
    }


def _release_production_learning_payload_with_content() -> Mapping[str, object]:
    return production_autonomous_learning_payload_from_baseline(
        "Samsung breakout strategy external evidence backed autonomous learning loop",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="real"),
        external_research=_release_content_external(),
    )


def _release_stage_payload(payload: Mapping[str, object], stage: str, checks: Mapping[str, bool]) -> dict[str, object]:
    learning = _as_dict(payload.get("autonomous_learning_v2"))
    loop = _as_dict(learning.get("production_loop"))
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "stage": stage,
        "promotion_status": payload.get("promotion_status"),
        "human_gate_status": payload.get("human_gate_status"),
        "grounded_evidence_count": loop.get("grounded_evidence_count"),
        "hypothesis_count": loop.get("hypothesis_count"),
        "candidate_experiment_count": loop.get("candidate_experiment_count"),
        "strategy_mutated": payload.get("strategy_mutated") is True,
        "order_executed": payload.get("order_executed") is True,
        "checks": dict(checks),
        "safety": payload.get("safety"),
    }


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def _fixture_academic_payload_is_blocked() -> bool:
    payload = production_autonomous_learning_payload_from_baseline(
        "fixture evidence must not promote",
        symbol="005930",
        mode="research",
        baseline=_release_baseline_payload(source="fixture"),
        external_research=_release_academic_content_external(),
    )
    return payload.get("approval_required") is False and payload.get("promotion_status") == "blocked_fixture"


def _fingerprint_mismatch_payload_is_blocked() -> bool:
    baseline = _release_baseline_payload(source="real")
    candidates = _as_list(baseline.get("candidates"))
    if candidates and isinstance(candidates[0], dict):
        strategy = candidates[0].get("strategy")
        if isinstance(strategy, dict):
            strategy["fingerprint"] = "fingerprint:mismatch"
        backtest = candidates[0].get("backtest_result")
        if isinstance(backtest, dict) and isinstance(backtest.get("strategy"), dict):
            backtest["strategy"] = dict(backtest["strategy"])
            backtest["strategy"]["fingerprint"] = "candidate-fingerprint-release-1854"
    payload = production_autonomous_learning_payload_from_baseline(
        "fingerprint mismatch must not promote",
        symbol="005930",
        mode="research",
        baseline=baseline,
        external_research=_release_academic_content_external(),
    )
    return (
        payload.get("approval_required") is False
        and payload.get("promotion_status") in {"blocked_fixture", "needs_real_validation"}
        and payload.get("candidate_strategy_fingerprint_matched") is False
    )


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
