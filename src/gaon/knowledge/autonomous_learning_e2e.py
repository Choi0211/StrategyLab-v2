"""Follow-up C - deterministic autonomous learning E2E release gate."""

from __future__ import annotations

import hashlib
import json
import tempfile
from typing import Mapping

from gaon.storage.foundation import GaonStorage

from .content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionPolicy,
    FetchPayload,
)
from .discovery import DiscoveryProvider, DiscoveryResult, DiscoveryStatus
from .discovery_ingestion import DiscoveryEvidenceIngestor
from .evidence_hypothesis import EvidenceBackedHypothesisGenerator
from .experiment_execution import (
    AuthoritativeExperimentExecutor,
    _fixture_experiment_and_backtest,
)
from .external_research_execution import (
    AutonomousExternalResearchExecutor,
    ExternalResearchExecutionPolicy,
)
from .external_research_memory import ExternalResearchMemoryRecord
from .gaps import (
    KnowledgeGapType,
    RequiredEvidence,
    RequiredEvidenceType,
    ResearchPriority,
    ResearchQuestion,
    ResearchStopCondition,
)
from .conflicts import ConflictStatus
from .execution import DiscoveryExecutionRun, QueryExecutionRecord
from .human_gated_promotion import HumanGatedPromotionService, HumanGatedPromotionStatus
from .promotion_gate import PromotionCandidateGate, PromotionGateStatus
from .provenance import SourceType


AUTONOMOUS_LEARNING_E2E_SCHEMA_VERSION = 1


def autonomous_learning_e2e_release_check() -> Mapping[str, object]:
    question = ResearchQuestion(
        question_id="research-question:e2e",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question="What independent evidence supports breakout robustness?",
        priority=ResearchPriority.HIGH,
        required_evidence=(
            RequiredEvidence(
                RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                1,
                "release check",
            ),
        ),
        stop_conditions=(ResearchStopCondition.TWO_INDEPENDENT_PRIMARY_SOURCES,),
        parent_conflict_id="knowledge-conflict:e2e",
        source_state=ConflictStatus.INSUFFICIENT_INDEPENDENCE,
    )
    with tempfile.TemporaryDirectory() as tmp:
        storage = GaonStorage(tmp)
        research = AutonomousExternalResearchExecutor(
            discovery_executor=_FixtureDiscoveryExecutor(),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(
                    network_enabled=True,
                    allowed_hosts=("example.org",),
                    max_content_bytes=8_000,
                ),
                transport=_FixtureTransport(),  # type: ignore[arg-type]
            ),
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=1,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        ).run(question)

    memory = _memory_from_research(research)
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="External evidence indicates robustness depends on regime context.",
        mechanism="A regime filter constrains entries before validation.",
        falsification_criteria=("Reject if authoritative backtest metrics do not support robustness.",),
    )
    experiment, backtest = _fixture_experiment_and_backtest(trade_count=60)
    execution = AuthoritativeExperimentExecutor().execute(experiment, backtest)
    promotion = PromotionCandidateGate().evaluate(
        execution.ranking,
        rollback_target="strategy-config:default:active",
        allow_fixture=True,
    )
    human_gate = HumanGatedPromotionService().evaluate(
        promotion,
        approval_token=None,
        signing_secret="release-check-secret",
        approved_by="actor:redacted",
        approved_at="2026-08-08T00:00:00+00:00",
        reason="release check",
    )
    checks = {
        "gap_to_question": question.parent_conflict_id.startswith("knowledge-conflict:"),
        "discovery_acquired": research.acquired_sources == 1,
        "claims_extracted": len(research.candidates) >= 1,
        "memory_created": memory.memory_id.startswith("external-research-memory:"),
        "hypothesis_proposed": hypothesis.status.value == "proposed",
        "experiment_validated": execution.validation.status.value == "accepted_for_review",
        "ranking_ready": execution.ranking.status.value == "ranked",
        "promotion_requires_approval": promotion.status is PromotionGateStatus.REQUIRES_HUMAN_APPROVAL,
        "human_gate_waiting": human_gate.status is HumanGatedPromotionStatus.AWAITING_HUMAN_APPROVAL,
        "no_mutation": not human_gate.strategy_mutated and not human_gate.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"autonomous learning e2e release check failed: {failed}")
    candidate_payload = promotion.to_json()
    hypothesis_payload = hypothesis.to_json()
    experiment_payload = experiment.to_json()
    evidence_payload = execution.evidence.to_json()
    validation_payload = execution.validation.to_json()
    ranking_payload = execution.ranking.to_json()
    external_research_payload = research.to_json()
    memory_payload = memory.to_json()
    return {
        "schema_version": AUTONOMOUS_LEARNING_E2E_SCHEMA_VERSION,
        "external_research_state": research.state.value,
        "claims": len(research.candidates),
        "hypothesis_status": hypothesis.status.value,
        "validation_status": execution.validation.status.value,
        "ranking_status": execution.ranking.status.value,
        "promotion_status": promotion.status.value,
        "human_gate_status": human_gate.status.value,
        "promotion_candidate": candidate_payload,
        "promotion_candidate_context": {
            "candidate_id": promotion.candidate_id,
            "candidate_fingerprint": _payload_fingerprint(candidate_payload),
            "baseline_strategy_id": experiment.baseline_strategy_id,
            "baseline_fingerprint": experiment.baseline_strategy_fingerprint,
            "hypothesis": hypothesis_payload,
            "changed_rules": list(hypothesis.changed_rules),
            "rationale": hypothesis.rationale,
            "expected_mechanism": hypothesis.mechanism,
            "falsification_criteria": list(hypothesis.falsification_criteria),
            "research_memory": memory_payload,
            "claim_ids": list(hypothesis.claim_ids),
            "source_ids": list(memory.source_ids),
            "source_lineage": _source_lineage(external_research_payload),
            "experiment": experiment_payload,
            "experiment_id": experiment.experiment_id,
            "experiment_fingerprint": _payload_fingerprint(experiment_payload),
            "assumptions_fingerprint": experiment.assumptions_fingerprint,
            "authoritative_validation_evidence": evidence_payload,
            "authoritative_backtest_result_id": evidence_payload["backtest_result_id"],
            "validation": validation_payload,
            "ranking": ranking_payload,
            "ranking_components": _ranking_components(ranking_payload),
            "blockers": list(promotion.blockers),
            "risks": _candidate_risks(external_research_payload, validation_payload, ranking_payload, candidate_payload),
            "human_gate": human_gate.to_json(),
            "approval_state": human_gate.status.value,
            "strategy_mutated": False,
            "order_executed": False,
            "broker_order_called": False,
            "kis_order_called": False,
        },
        "checks": checks,
        "safety": "pass",
    }


class _FixtureDiscoveryExecutor:
    def execute(self, plan):  # type: ignore[no-untyped-def]
        result = DiscoveryResult(
            result_id="discovery-result:e2e",
            query_id=plan.queries[0].query_id,
            provider=DiscoveryProvider.ACADEMIC_SEARCH,
            title="Fixture research",
            locator="https://example.org/research.html",
            source_type=SourceType.RESEARCH_REPORT,
            status=DiscoveryStatus.DISCOVERED,
        )
        return DiscoveryExecutionRun(
            run_id="source-discovery-run:e2e",
            plan_id=plan.plan_id,
            network_enabled=False,
            network_executed=False,
            provider_calls=1,
            results=(result,),
            query_records=(
                QueryExecutionRecord(
                    plan.queries[0].query_id,
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    DiscoveryStatus.DISCOVERED,
                    1,
                    1,
                    1,
                ),
            ),
            duplicate_results=0,
            budget_exhausted=False,
        )


class _FixtureTransport:
    def fetch(self, target, *, policy):  # type: ignore[no-untyped-def]
        return FetchPayload(
            final_url=target.content_url,
            content_type="text/html",
            content=b"<article>Claim: breakout robustness improves when regime filters are validated.</article>",
        )


def _memory_from_research(research) -> ExternalResearchMemoryRecord:  # type: ignore[no-untyped-def]
    payload = research.to_json()
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    conflict_status = None
    if research.reevaluation and research.reevaluation.conflict:
        conflict_status = research.reevaluation.conflict.status.value
    return ExternalResearchMemoryRecord(
        memory_id=f"external-research-memory:{fingerprint}",
        fingerprint=fingerprint,
        topic_key="strategy.breakout.robustness",
        loop_id="autonomous-external-research:e2e",
        conflict_status=conflict_status,
        claim_ids=tuple(candidate.claim_id for candidate in research.candidates),
        question_ids=("research-question:e2e",),
        source_ids=tuple(sorted({candidate.source_id for candidate in research.candidates})),
        created_at="2026-08-08T00:00:00+00:00",
    )


def _payload_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_lineage(external_research: Mapping[str, object]) -> list[dict[str, object]]:
    discovery = external_research.get("discovery_run")
    discovery_results = discovery.get("results", []) if isinstance(discovery, dict) else []
    normalized = external_research.get("normalized_records")
    normalized_records = normalized if isinstance(normalized, list) else []
    candidates = external_research.get("candidates")
    candidate_records = candidates if isinstance(candidates, list) else []
    normalized_source_ids = {
        str(record.get("source_id"))
        for record in normalized_records
        if isinstance(record, dict) and record.get("source_id") is not None
    }
    lineage: list[dict[str, object]] = []
    for result in discovery_results:
        if not isinstance(result, dict):
            continue
        result_id = str(result.get("result_id", ""))
        source_ids = sorted(
            {
                str(candidate.get("source_id"))
                for candidate in candidate_records
                if isinstance(candidate, dict) and candidate.get("source_id") is not None
            }
        )
        claim_ids = sorted(
            {
                str(candidate.get("claim_id"))
                for candidate in candidate_records
                if isinstance(candidate, dict) and candidate.get("claim_id") is not None
            }
        )
        lineage.append(
            {
                "discovery_result_id": result_id,
                "title": result.get("title"),
                "source_type": result.get("source_type"),
                "locator": result.get("locator"),
                "source_ids": source_ids,
                "claim_ids": claim_ids,
                "metadata_only": not any(source_id in normalized_source_ids for source_id in source_ids),
                "content_acquired": any(source_id in normalized_source_ids for source_id in source_ids),
            }
        )
    return lineage


def _ranking_components(ranking: Mapping[str, object]) -> dict[str, object]:
    ranked = ranking.get("ranked")
    rows = ranked if isinstance(ranked, list) else []
    top = rows[0] if rows and isinstance(rows[0], dict) else {}
    components: dict[str, object] = {}
    for key in ("score", "trade_count", "total_return", "mdd", "profit_factor", "win_rate", "source", "fixture_backed"):
        if key in top:
            components[key] = top[key]
    if ranking.get("status") is not None:
        components["ranking_status"] = ranking["status"]
    warnings = ranking.get("warnings")
    if isinstance(warnings, list):
        components["warnings"] = warnings
    return components


def _candidate_risks(
    external_research: Mapping[str, object],
    validation: Mapping[str, object],
    ranking: Mapping[str, object],
    candidate: Mapping[str, object],
) -> list[str]:
    risks: list[str] = []
    blockers = candidate.get("blockers")
    if isinstance(blockers, list):
        risks.extend(str(item) for item in blockers)
    validation_warnings = validation.get("warnings")
    if isinstance(validation_warnings, list):
        risks.extend(str(item) for item in validation_warnings)
    ranking_warnings = ranking.get("warnings")
    if isinstance(ranking_warnings, list):
        risks.extend(str(item) for item in ranking_warnings)
    external_blockers = external_research.get("blockers")
    if isinstance(external_blockers, list):
        risks.extend(str(item) for item in external_blockers)
    return list(dict.fromkeys(risks))
