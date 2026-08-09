"""Follow-up A - autonomous external research execution orchestration.

This module wires the existing discovery, ingestion, acquisition,
normalization, claim bridging, and reevaluation components into one bounded
execution path. It does not introduce new provider systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol

from .content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionPolicy,
    ContentAcquisitionStatus,
    ContentAcquisitionTarget,
)
from .content_claim_bridge import ContentClaimBridgeStatus, NormalizedContentClaimBridge
from .content_normalization import NormalizedContentRecord, SafeContentNormalizer
from .discovery import DiscoveryBudget, DiscoveryPolicy, DiscoveryStatus, SourceDiscoveryPlanner
from .discovery_ingestion import DiscoveryEvidenceIngestor
from .evidence_reevaluation import EvidenceConflictReevaluator, EvidenceReevaluationResult
from .execution import BoundedSourceDiscoveryExecutor, DiscoveryExecutionRun
from .gaps import ResearchQuestion
from .claims import KnowledgeCandidate
from .conflicts import ClaimStance
from .provenance import SourceProvenance


EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION = 1


class ExternalResearchTerminalState(str, Enum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    NO_NEW_RESEARCH_PATH = "no_new_research_path"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_FAILURE = "provider_failure"
    CONTENT_UNAVAILABLE = "content_unavailable"
    DATA_FAILURE = "data_failure"


@dataclass(frozen=True)
class ExternalResearchExecutionPolicy:
    max_iterations: int = 1
    max_provider_calls: int = 2
    max_sources: int = 2
    max_total_download_bytes: int = 64_000
    content_network_enabled: bool = False
    allowed_content_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.max_provider_calls <= 0:
            raise ValueError("max_provider_calls must be positive")
        if self.max_sources <= 0:
            raise ValueError("max_sources must be positive")
        if self.max_total_download_bytes <= 0:
            raise ValueError("max_total_download_bytes must be positive")


class ContentResolver(Protocol):
    def content_url_for(self, result_locator: str) -> str | None: ...


class LocatorContentResolver:
    """Resolves only direct HTTPS content locators.

    DOI and metadata-only locators intentionally return None so the caller can
    report content_unavailable instead of pretending content was fetched.
    """

    def content_url_for(self, result_locator: str) -> str | None:
        value = result_locator.strip()
        if value.startswith("https://"):
            return value
        return None


@dataclass(frozen=True)
class AutonomousExternalResearchExecutionResult:
    state: ExternalResearchTerminalState
    question_id: str
    discovery_run: DiscoveryExecutionRun | None
    normalized_records: tuple[NormalizedContentRecord, ...]
    candidates: tuple[KnowledgeCandidate, ...]
    reevaluation: EvidenceReevaluationResult | None
    provider_calls: int
    acquired_sources: int
    downloaded_bytes: int
    duplicate_results: int
    blockers: tuple[str, ...]
    network_executed: bool
    production_approved: bool = False
    knowledge_validated: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
            "state": self.state.value,
            "question_id": self.question_id,
            "discovery_run": self.discovery_run.to_json() if self.discovery_run else None,
            "normalized_records": [item.to_json() for item in self.normalized_records],
            "candidates": [item.to_json() for item in self.candidates],
            "reevaluation": self.reevaluation.to_json() if self.reevaluation else None,
            "provider_calls": self.provider_calls,
            "acquired_sources": self.acquired_sources,
            "downloaded_bytes": self.downloaded_bytes,
            "duplicate_results": self.duplicate_results,
            "blockers": list(self.blockers),
            "network_executed": self.network_executed,
            "production_approved": self.production_approved,
            "knowledge_validated": self.knowledge_validated,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class AutonomousExternalResearchExecutor:
    def __init__(
        self,
        *,
        planner: SourceDiscoveryPlanner | None = None,
        discovery_executor: BoundedSourceDiscoveryExecutor | None = None,
        ingestion: DiscoveryEvidenceIngestor | None = None,
        acquirer: BoundedSourceContentAcquirer | None = None,
        normalizer: SafeContentNormalizer | None = None,
        claim_bridge: NormalizedContentClaimBridge | None = None,
        reevaluator: EvidenceConflictReevaluator | None = None,
        resolver: ContentResolver | None = None,
        policy: ExternalResearchExecutionPolicy | None = None,
    ) -> None:
        self.policy = policy or ExternalResearchExecutionPolicy()
        self.planner = planner or SourceDiscoveryPlanner(
            budget=DiscoveryBudget(
                max_queries=self.policy.max_provider_calls,
                max_results_per_query=self.policy.max_sources,
                max_total_results=self.policy.max_sources,
            )
        )
        self.discovery_executor = discovery_executor or BoundedSourceDiscoveryExecutor()
        self.ingestion = ingestion or DiscoveryEvidenceIngestor()
        self.acquirer = acquirer or BoundedSourceContentAcquirer(
            policy=ContentAcquisitionPolicy(
                network_enabled=self.policy.content_network_enabled,
                allowed_hosts=self.policy.allowed_content_hosts,
                max_content_bytes=self.policy.max_total_download_bytes,
            )
        )
        self.normalizer = normalizer or SafeContentNormalizer()
        self.claim_bridge = claim_bridge or NormalizedContentClaimBridge()
        self.reevaluator = reevaluator or EvidenceConflictReevaluator()
        self.resolver = resolver or LocatorContentResolver()

    def run(
        self,
        question: ResearchQuestion,
        *,
        existing_candidates: tuple[KnowledgeCandidate, ...] = (),
        stances: Mapping[str, ClaimStance] | None = None,
    ) -> AutonomousExternalResearchExecutionResult:
        blockers: list[str] = []
        normalized: list[NormalizedContentRecord] = []
        candidates: list[KnowledgeCandidate] = []
        downloaded_bytes = 0
        acquired = 0
        seen_results: set[str] = set()

        plan = self.planner.build(question)
        execution = self.discovery_executor.execute(plan)
        if execution.provider_calls > self.policy.max_provider_calls:
            return self._result(ExternalResearchTerminalState.BUDGET_EXHAUSTED, question, execution, (), (), None, blockers, 0, 0)
        if not execution.results:
            state = (
                ExternalResearchTerminalState.PROVIDER_FAILURE
                if any(record.failure_kind for record in execution.query_records)
                else ExternalResearchTerminalState.NO_NEW_RESEARCH_PATH
            )
            return self._result(state, question, execution, (), (), None, blockers, 0, 0)

        try:
            self.ingestion.ingest_execution(execution)
        except ValueError as exc:
            blockers.append(f"discovery_ingestion_blocked:{exc}")

        source_by_id: dict[str, SourceProvenance] = {}
        for result in execution.results[: self.policy.max_sources]:
            if result.result_id in seen_results:
                continue
            seen_results.add(result.result_id)
            content_url = self.resolver.content_url_for(result.locator)
            if content_url is None:
                blockers.append(f"content_unavailable:{result.result_id}")
                continue
            target = ContentAcquisitionTarget.from_discovery(result, content_url=content_url)
            acquisition = self.acquirer.acquire(target)
            if acquisition.status is not ContentAcquisitionStatus.ACQUIRED:
                blockers.append(f"content_unavailable:{result.result_id}:{acquisition.failure_kind.value if acquisition.failure_kind else 'failed'}")
                continue
            downloaded_bytes += acquisition.byte_count
            if downloaded_bytes > self.policy.max_total_download_bytes:
                blockers.append("budget_exhausted:download_bytes")
                return self._result(ExternalResearchTerminalState.BUDGET_EXHAUSTED, question, execution, tuple(normalized), tuple(candidates), None, blockers, acquired, downloaded_bytes)
            acquired += 1
            source = SourceProvenance.create(
                source_type=result.source_type,
                title=result.title,
                locator=acquisition.final_url,
                content_sha256=acquisition.content_sha256,
                trust_level=source_trust_level(result.source_type),
                ingested_at="2026-08-08T00:00:00+00:00",
                notes=f"discovery_result_id={result.result_id}",
            )
            source_by_id[acquisition.source_id] = source
            record = self.normalizer.normalize(acquisition, self._content_for(acquisition))
            normalized.append(record)
            bridge = self.claim_bridge.extract(record, source)
            if bridge.status is not ContentClaimBridgeStatus.EXTRACTED:
                blockers.append(f"claim_bridge_failed:{result.result_id}:{bridge.status.value}")
                continue
            candidates.extend(bridge.candidates)

        if blockers and not candidates:
            return self._result(ExternalResearchTerminalState.CONTENT_UNAVAILABLE, question, execution, tuple(normalized), (), None, blockers, acquired, downloaded_bytes)
        if not candidates:
            return self._result(ExternalResearchTerminalState.NO_NEW_RESEARCH_PATH, question, execution, tuple(normalized), (), None, blockers, acquired, downloaded_bytes)

        combined_candidates = tuple(existing_candidates) + tuple(candidates)
        reevaluation = self.reevaluator.reevaluate(
            topic_key=question.topic_key,
            candidates=combined_candidates,
            stances=stances or {candidate.candidate_id: ClaimStance.SUPPORTS for candidate in candidates},
        )
        if reevaluation.blockers:
            state = ExternalResearchTerminalState.DATA_FAILURE
        elif reevaluation.conflict is None or reevaluation.conflict.status.value == "no_conflict":
            state = ExternalResearchTerminalState.EVIDENCE_SUFFICIENT
        else:
            state = ExternalResearchTerminalState.UNRESOLVED_CONFLICT
        return self._result(state, question, execution, tuple(normalized), tuple(candidates), reevaluation, blockers, acquired, downloaded_bytes)

    def _content_for(self, acquisition: object) -> bytes:
        path = getattr(acquisition, "raw_path", "")
        if path:
            try:
                from pathlib import Path
                return Path(path).read_bytes()
            except OSError:
                pass
        return b""

    @staticmethod
    def _result(
        state: ExternalResearchTerminalState,
        question: ResearchQuestion,
        execution: DiscoveryExecutionRun | None,
        normalized: tuple[NormalizedContentRecord, ...],
        candidates: tuple[KnowledgeCandidate, ...],
        reevaluation: EvidenceReevaluationResult | None,
        blockers: list[str],
        acquired: int,
        downloaded_bytes: int,
    ) -> AutonomousExternalResearchExecutionResult:
        return AutonomousExternalResearchExecutionResult(
            state=state,
            question_id=question.question_id,
            discovery_run=execution,
            normalized_records=normalized,
            candidates=candidates,
            reevaluation=reevaluation,
            provider_calls=execution.provider_calls if execution else 0,
            acquired_sources=acquired,
            downloaded_bytes=downloaded_bytes,
            duplicate_results=execution.duplicate_results if execution else 0,
            blockers=tuple(blockers),
            network_executed=bool(execution and execution.network_executed),
        )


def autonomous_external_research_execution_release_check() -> Mapping[str, object]:
    import tempfile

    from .discovery import DiscoveryProvider, DiscoveryResult
    from .execution import DiscoveryExecutionRun, QueryExecutionRecord
    from .conflicts import ConflictStatus
    from .gaps import KnowledgeGapType, RequiredEvidence, RequiredEvidenceType, ResearchPriority, ResearchQuestion, ResearchStopCondition
    from .provenance import SourceType
    from .content_acquisition import FetchPayload
    from .discovery_ingestion import DiscoveryEvidenceIngestor
    from gaon.storage.foundation import GaonStorage

    class FixtureDiscoveryExecutor:
        def execute(self, plan):  # type: ignore[no-untyped-def]
            result = DiscoveryResult(
                result_id="discovery-result:fixture",
                query_id=plan.queries[0].query_id,
                provider=DiscoveryProvider.ACADEMIC_SEARCH,
                title="Fixture research",
                locator="https://example.org/research.html",
                source_type=SourceType.RESEARCH_REPORT,
                status=DiscoveryStatus.DISCOVERED,
            )
            return DiscoveryExecutionRun(
                run_id="source-discovery-run:fixture",
                plan_id=plan.plan_id,
                network_enabled=False,
                network_executed=False,
                provider_calls=1,
                results=(result,),
                query_records=(QueryExecutionRecord(plan.queries[0].query_id, DiscoveryProvider.ACADEMIC_SEARCH, DiscoveryStatus.DISCOVERED, 1, 1, 1),),
                duplicate_results=0,
                budget_exhausted=False,
            )

    class FixtureTransport:
        def fetch(self, target, *, policy):  # type: ignore[no-untyped-def]
            return FetchPayload(
                final_url=target.content_url,
                content_type="text/html",
                content=b"<html><body>Claim: breakout filters can reduce false signals.</body></html>",
            )

    question = ResearchQuestion(
        question_id="research-question:external-execution",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question="What evidence supports breakout robustness?",
        priority=ResearchPriority.HIGH,
        required_evidence=(RequiredEvidence(RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE, 1, "release check"),),
        stop_conditions=(ResearchStopCondition.TWO_INDEPENDENT_PRIMARY_SOURCES,),
        parent_conflict_id="knowledge-conflict:external-execution",
        source_state=ConflictStatus.INSUFFICIENT_INDEPENDENCE,
    )
    with tempfile.TemporaryDirectory() as tmp:
        storage = GaonStorage(tmp)
        executor = AutonomousExternalResearchExecutor(
            discovery_executor=FixtureDiscoveryExecutor(),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(
                    network_enabled=True,
                    allowed_hosts=("example.org",),
                    max_content_bytes=8_000,
                ),
                transport=FixtureTransport(),  # type: ignore[arg-type]
            ),
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=1,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        )
        result = executor.run(question)
    checks = {
        "discovery": result.discovery_run is not None and len(result.discovery_run.results) == 1,
        "acquisition": result.acquired_sources == 1,
        "normalization": len(result.normalized_records) == 1,
        "claims": len(result.candidates) >= 1,
        "reevaluation": result.reevaluation is not None,
        "no_mutation": not result.strategy_mutated and not result.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"autonomous external research execution release check failed: {failed}")
    return {
        "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
        "state": result.state.value,
        "provider_calls": result.provider_calls,
        "sources": result.acquired_sources,
        "claims": len(result.candidates),
        "checks": checks,
        "safety": "pass",
    }


def source_trust_level(source_type: object):
    from .provenance import SourceType, TrustLevel

    if source_type in (SourceType.ACADEMIC_PAPER, SourceType.OFFICIAL_DOCUMENT, SourceType.DATASET):
        return TrustLevel.HIGH
    if source_type is SourceType.RESEARCH_REPORT:
        return TrustLevel.MODERATE
    return TrustLevel.UNKNOWN
