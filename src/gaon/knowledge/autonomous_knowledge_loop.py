"""Sprint 178 - Autonomous Knowledge Research Loop.

Runs a bounded evidence loop over already supplied/acquired inert content.

Safety invariants:
- no network access is opened by this loop
- downloaded/source content remains evidence, never instruction
- loop output is not Knowledge Validated
- no strategy mutation, Champion promotion, approval bypass, or trading
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

from .claims import KnowledgeCandidate
from .conflicts import ClaimStance, ConflictStatus
from .content_acquisition import (
    ContentAcquisitionRecord,
    ContentAcquisitionStatus,
)
from .content_claim_bridge import (
    ContentClaimBridgeResult,
    ContentClaimBridgeStatus,
    NormalizedContentClaimBridge,
)
from .content_normalization import SafeContentNormalizer
from .evidence_reevaluation import (
    EvidenceConflictReevaluator,
    EvidenceReevaluationResult,
    EvidenceReevaluationStatus,
)
from .gaps import ResearchQuestion
from .provenance import SourceProvenance, SourceType, TrustLevel


AUTONOMOUS_KNOWLEDGE_LOOP_SCHEMA_VERSION = 1


class KnowledgeResearchLoopStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class KnowledgeResearchLoopBlocker(str, Enum):
    NO_EVIDENCE = "no_evidence"
    BYTE_BUDGET_EXCEEDED = "byte_budget_exceeded"
    CLAIM_EXTRACTION_BLOCKED = "claim_extraction_blocked"
    REEVALUATION_BLOCKED = "reevaluation_blocked"


@dataclass(frozen=True)
class KnowledgeResearchLoopPolicy:
    max_sources: int = 5
    max_total_bytes: int = 5 * 1024 * 1024
    max_iterations: int = 5

    def __post_init__(self) -> None:
        if self.max_sources <= 0:
            raise ValueError("max_sources must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")


@dataclass(frozen=True)
class SourceEvidenceInput:
    source: SourceProvenance
    content: bytes
    content_type: str
    stance: ClaimStance


@dataclass(frozen=True)
class KnowledgeResearchLoopResult:
    schema_version: int
    loop_id: str
    topic_key: str
    status: KnowledgeResearchLoopStatus
    processed_sources: int
    total_bytes: int
    bridge_results: tuple[ContentClaimBridgeResult, ...]
    reevaluation: EvidenceReevaluationResult | None
    research_questions: tuple[ResearchQuestion, ...]
    blockers: tuple[KnowledgeResearchLoopBlocker, ...]
    network_used: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    @property
    def candidates(self) -> tuple[KnowledgeCandidate, ...]:
        return tuple(
            candidate
            for bridge in self.bridge_results
            for candidate in bridge.candidates
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "loop_id": self.loop_id,
            "topic_key": self.topic_key,
            "status": self.status.value,
            "processed_sources": self.processed_sources,
            "total_bytes": self.total_bytes,
            "bridge_results": [
                item.to_json()
                for item in self.bridge_results
            ],
            "reevaluation": (
                self.reevaluation.to_json()
                if self.reevaluation is not None
                else None
            ),
            "research_questions": [
                item.to_json()
                for item in self.research_questions
            ],
            "blockers": [item.value for item in self.blockers],
            "network_used": self.network_used,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def canonical_loop_id(
    *,
    topic_key: str,
    inputs: tuple[SourceEvidenceInput, ...],
) -> str:
    encoded = json.dumps(
        {
            "topic_key": topic_key.strip().lower(),
            "source_ids": [item.source.source_id for item in inputs],
            "content_sha256": [
                hashlib.sha256(item.content).hexdigest()
                for item in inputs
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"knowledge-research-loop:{hashlib.sha256(encoded).hexdigest()}"


class AutonomousKnowledgeResearchLoop:
    """Bounded deterministic research loop over explicit evidence inputs."""

    def __init__(
        self,
        *,
        policy: KnowledgeResearchLoopPolicy | None = None,
        normalizer: SafeContentNormalizer | None = None,
        bridge: NormalizedContentClaimBridge | None = None,
        reevaluator: EvidenceConflictReevaluator | None = None,
    ) -> None:
        self.policy = policy or KnowledgeResearchLoopPolicy()
        self._normalizer = normalizer or SafeContentNormalizer()
        self._bridge = bridge or NormalizedContentClaimBridge()
        self._reevaluator = reevaluator or EvidenceConflictReevaluator()

    def run(
        self,
        *,
        topic_key: str,
        evidence: tuple[SourceEvidenceInput, ...],
    ) -> KnowledgeResearchLoopResult:
        loop_id = canonical_loop_id(topic_key=topic_key, inputs=evidence)
        if not evidence:
            return self._blocked(
                loop_id,
                topic_key,
                (),
                (KnowledgeResearchLoopBlocker.NO_EVIDENCE,),
                0,
            )

        selected = evidence[: self.policy.max_sources]
        status = (
            KnowledgeResearchLoopStatus.BUDGET_EXHAUSTED
            if len(evidence) > len(selected)
            else KnowledgeResearchLoopStatus.COMPLETED
        )
        total_bytes = sum(len(item.content) for item in selected)
        if total_bytes > self.policy.max_total_bytes:
            return self._blocked(
                loop_id,
                topic_key,
                (),
                (KnowledgeResearchLoopBlocker.BYTE_BUDGET_EXCEEDED,),
                total_bytes,
            )

        bridge_results: list[ContentClaimBridgeResult] = []
        stances: dict[str, ClaimStance] = {}
        candidates: list[KnowledgeCandidate] = []
        for index, item in enumerate(selected[: self.policy.max_iterations]):
            acquisition = self._acquisition_record(index, item)
            normalized = self._normalizer.normalize(acquisition, item.content)
            bridge_result = self._bridge.extract(normalized, item.source)
            bridge_results.append(bridge_result)
            if bridge_result.status is not ContentClaimBridgeStatus.EXTRACTED:
                return self._blocked(
                    loop_id,
                    topic_key,
                    tuple(bridge_results),
                    (KnowledgeResearchLoopBlocker.CLAIM_EXTRACTION_BLOCKED,),
                    total_bytes,
                )
            for candidate in bridge_result.candidates:
                candidates.append(candidate)
                stances[candidate.candidate_id] = item.stance

        reevaluation = self._reevaluator.reevaluate(
            topic_key=topic_key,
            candidates=tuple(candidates),
            stances=stances,
        )
        if reevaluation.status is EvidenceReevaluationStatus.BLOCKED:
            return self._blocked(
                loop_id,
                topic_key,
                tuple(bridge_results),
                (KnowledgeResearchLoopBlocker.REEVALUATION_BLOCKED,),
                total_bytes,
                reevaluation,
            )

        return KnowledgeResearchLoopResult(
            schema_version=AUTONOMOUS_KNOWLEDGE_LOOP_SCHEMA_VERSION,
            loop_id=loop_id,
            topic_key=topic_key.strip().lower(),
            status=status,
            processed_sources=len(bridge_results),
            total_bytes=total_bytes,
            bridge_results=tuple(bridge_results),
            reevaluation=reevaluation,
            research_questions=reevaluation.research_questions,
            blockers=(),
        )

    @staticmethod
    def _acquisition_record(
        index: int,
        item: SourceEvidenceInput,
    ) -> ContentAcquisitionRecord:
        digest = hashlib.sha256(item.content).hexdigest()
        return ContentAcquisitionRecord(
            acquisition_id=f"content-acquisition:loop:{index}:{digest}",
            discovery_result_id=f"discovery-result:loop:{index}",
            source_locator=item.source.locator,
            content_url=item.source.locator,
            final_url=item.source.locator,
            content_type=item.content_type,
            byte_count=len(item.content),
            content_sha256=digest,
            status=ContentAcquisitionStatus.ACQUIRED,
            failure_kind=None,
            error_message=None,
            source_id=item.source.source_id,
            raw_path=None,
            metadata_path=None,
            actual_source_body_fetched=True,
            stored_as_inert_evidence=True,
        )

    @staticmethod
    def _blocked(
        loop_id: str,
        topic_key: str,
        bridge_results: tuple[ContentClaimBridgeResult, ...],
        blockers: tuple[KnowledgeResearchLoopBlocker, ...],
        total_bytes: int,
        reevaluation: EvidenceReevaluationResult | None = None,
    ) -> KnowledgeResearchLoopResult:
        return KnowledgeResearchLoopResult(
            schema_version=AUTONOMOUS_KNOWLEDGE_LOOP_SCHEMA_VERSION,
            loop_id=loop_id,
            topic_key=topic_key.strip().lower(),
            status=KnowledgeResearchLoopStatus.BLOCKED,
            processed_sources=len(bridge_results),
            total_bytes=total_bytes,
            bridge_results=bridge_results,
            reevaluation=reevaluation,
            research_questions=(),
            blockers=blockers,
        )


def autonomous_knowledge_research_loop_release_check() -> Mapping[str, object]:
    def source(title: str, locator: str, text: str) -> SourceProvenance:
        return SourceProvenance.create(
            source_type=SourceType.ACADEMIC_PAPER,
            title=title,
            locator=locator,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            trust_level=TrustLevel.HIGH,
            author="Researcher",
            publisher="Journal",
            published_at="2026-01-01",
            license_name="test-only",
            ingested_at="2026-08-08T00:00:00+00:00",
        )

    support_text = "Breakout filters can improve trend robustness across regimes."
    oppose_text = "Breakout filters can reduce trend robustness across regimes."
    evidence = (
        SourceEvidenceInput(
            source("Support", "https://example.invalid/loop/support", support_text),
            support_text.encode("utf-8"),
            "text/plain",
            ClaimStance.SUPPORTS,
        ),
        SourceEvidenceInput(
            source("Oppose", "https://example.invalid/loop/oppose", oppose_text),
            oppose_text.encode("utf-8"),
            "text/plain",
            ClaimStance.OPPOSES,
        ),
    )
    result = AutonomousKnowledgeResearchLoop().run(
        topic_key="strategy.breakout.robustness",
        evidence=evidence,
    )
    blocked = AutonomousKnowledgeResearchLoop(
        policy=KnowledgeResearchLoopPolicy(max_total_bytes=8)
    ).run(
        topic_key="strategy.breakout.robustness",
        evidence=evidence,
    )

    checks = {
        "completed": result.status is KnowledgeResearchLoopStatus.COMPLETED,
        "sources_processed": result.processed_sources == 2,
        "claims_created": len(result.candidates) == 2,
        "conflict_detected": result.reevaluation is not None
        and result.reevaluation.conflict is not None
        and result.reevaluation.conflict.status
        is ConflictStatus.UNRESOLVED_CONFLICT,
        "questions_generated": len(result.research_questions) == 1,
        "network_not_used": not result.network_used,
        "not_validated": not result.knowledge_validated,
        "no_mutation": not result.strategy_mutated and not result.order_executed,
        "byte_budget_blocked":
            KnowledgeResearchLoopBlocker.BYTE_BUDGET_EXCEEDED
            in blocked.blockers,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"autonomous knowledge research loop release check failed: {failed}"
        )

    return {
        "schema_version": AUTONOMOUS_KNOWLEDGE_LOOP_SCHEMA_VERSION,
        "status": result.status.value,
        "processed_sources": result.processed_sources,
        "claims": len(result.candidates),
        "questions": len(result.research_questions),
        "checks": checks,
        "safety": "pass",
    }

