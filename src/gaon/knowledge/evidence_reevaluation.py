"""Sprint 177 - Evidence Conflict Re-evaluation.

Re-evaluates structured claim evidence as new candidates arrive.

Safety invariants:
- claim stance is explicit, never inferred from text
- conflict detection does not resolve disagreements automatically
- research questions are not answers
- no Knowledge Validated transition
- no strategy mutation, Champion promotion, or trading
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable, Mapping

from .claims import KnowledgeCandidate
from .conflicts import (
    ClaimStance,
    ConflictStatus,
    KnowledgeConflictDetector,
    KnowledgeConflictRecord,
    PositionedClaim,
)
from .gaps import ResearchQuestion, ResearchQuestionGenerator


EVIDENCE_REEVALUATION_SCHEMA_VERSION = 1


class EvidenceReevaluationStatus(str, Enum):
    REEVALUATED = "reevaluated"
    BLOCKED = "blocked"


class EvidenceReevaluationBlocker(str, Enum):
    NO_CANDIDATES = "no_candidates"
    MISSING_STANCE = "missing_stance"
    MIXED_TOPIC = "mixed_topic"
    VALIDATED_OR_APPROVED_INPUT = "validated_or_approved_input"


@dataclass(frozen=True)
class EvidenceReevaluationResult:
    schema_version: int
    reevaluation_id: str
    topic_key: str
    status: EvidenceReevaluationStatus
    positioned_claims: tuple[PositionedClaim, ...]
    conflict: KnowledgeConflictRecord | None
    research_questions: tuple[ResearchQuestion, ...]
    blockers: tuple[EvidenceReevaluationBlocker, ...]
    prior_conflict_status: ConflictStatus | None = None
    conflict_status_changed: bool = False
    automatic_resolution: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "reevaluation_id": self.reevaluation_id,
            "topic_key": self.topic_key,
            "status": self.status.value,
            "positioned_claims": [
                item.__dict__ | {"stance": item.stance.value}
                for item in self.positioned_claims
            ],
            "conflict": (
                self.conflict.to_json()
                if self.conflict is not None
                else None
            ),
            "research_questions": [
                item.to_json()
                for item in self.research_questions
            ],
            "blockers": [item.value for item in self.blockers],
            "prior_conflict_status": (
                self.prior_conflict_status.value
                if self.prior_conflict_status
                else None
            ),
            "conflict_status_changed": self.conflict_status_changed,
            "automatic_resolution": self.automatic_resolution,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def canonical_reevaluation_id(
    *,
    topic_key: str,
    candidates: Iterable[KnowledgeCandidate],
) -> str:
    topic = topic_key.strip().lower()
    candidate_ids = sorted(candidate.candidate_id for candidate in candidates)
    encoded = json.dumps(
        {"topic_key": topic, "candidate_ids": candidate_ids},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"evidence-reevaluation:{hashlib.sha256(encoded).hexdigest()}"


class EvidenceConflictReevaluator:
    """Re-runs conflict and gap analysis for explicit positioned evidence."""

    def __init__(
        self,
        *,
        conflict_detector: KnowledgeConflictDetector | None = None,
        question_generator: ResearchQuestionGenerator | None = None,
    ) -> None:
        self._conflict_detector = conflict_detector or KnowledgeConflictDetector()
        self._question_generator = question_generator or ResearchQuestionGenerator()

    def reevaluate(
        self,
        *,
        topic_key: str,
        candidates: Iterable[KnowledgeCandidate],
        stances: Mapping[str, ClaimStance],
        prior_conflict: KnowledgeConflictRecord | None = None,
    ) -> EvidenceReevaluationResult:
        topic = topic_key.strip().lower()
        items = tuple(candidates)
        reevaluation_id = canonical_reevaluation_id(
            topic_key=topic,
            candidates=items,
        )
        blockers = self._blockers(items, stances)
        if blockers:
            return EvidenceReevaluationResult(
                schema_version=EVIDENCE_REEVALUATION_SCHEMA_VERSION,
                reevaluation_id=reevaluation_id,
                topic_key=topic,
                status=EvidenceReevaluationStatus.BLOCKED,
                positioned_claims=(),
                conflict=None,
                research_questions=(),
                blockers=tuple(blockers),
                prior_conflict_status=(
                    prior_conflict.status if prior_conflict else None
                ),
            )

        positioned = tuple(
            PositionedClaim.from_candidate(
                candidate,
                topic_key=topic,
                stance=stances[candidate.candidate_id],
            )
            for candidate in items
        )
        conflict = self._conflict_detector.evaluate(topic, positioned)
        questions = self._question_generator.generate(conflict)

        prior_status = prior_conflict.status if prior_conflict else None
        return EvidenceReevaluationResult(
            schema_version=EVIDENCE_REEVALUATION_SCHEMA_VERSION,
            reevaluation_id=reevaluation_id,
            topic_key=topic,
            status=EvidenceReevaluationStatus.REEVALUATED,
            positioned_claims=positioned,
            conflict=conflict,
            research_questions=questions,
            blockers=(),
            prior_conflict_status=prior_status,
            conflict_status_changed=(
                prior_status is not None and prior_status is not conflict.status
            ),
            automatic_resolution=False,
        )

    @staticmethod
    def _blockers(
        candidates: tuple[KnowledgeCandidate, ...],
        stances: Mapping[str, ClaimStance],
    ) -> list[EvidenceReevaluationBlocker]:
        blockers: list[EvidenceReevaluationBlocker] = []
        if not candidates:
            blockers.append(EvidenceReevaluationBlocker.NO_CANDIDATES)
        if any(candidate.candidate_id not in stances for candidate in candidates):
            blockers.append(EvidenceReevaluationBlocker.MISSING_STANCE)
        if any(
            candidate.knowledge_validated or candidate.production_approved
            for candidate in candidates
        ):
            blockers.append(
                EvidenceReevaluationBlocker.VALIDATED_OR_APPROVED_INPUT
            )
        return blockers


def evidence_conflict_reevaluation_release_check() -> Mapping[str, object]:
    from .claims import KnowledgeCandidateBuilder, VerbatimClaimExtractor
    from .provenance import SourceProvenance, SourceType, TrustLevel
    from .quality import SourceQualityEvaluator

    def build_candidate(title: str, locator: str, text: str) -> KnowledgeCandidate:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source = SourceProvenance.create(
            source_type=SourceType.ACADEMIC_PAPER,
            title=title,
            locator=locator,
            content_sha256=digest,
            trust_level=TrustLevel.HIGH,
            author="Researcher",
            publisher="Journal",
            published_at="2026-01-01",
            license_name="test-only",
            ingested_at="2026-08-08T00:00:00+00:00",
        )
        claim = VerbatimClaimExtractor(max_claims=1).extract(source, text)[0]
        quality = SourceQualityEvaluator().evaluate(source)
        return KnowledgeCandidateBuilder().build(claim, quality)

    support = build_candidate(
        "Support Evidence",
        "https://example.invalid/support",
        "Breakout filters can improve trend following robustness.",
    )
    oppose = build_candidate(
        "Opposing Evidence",
        "https://example.invalid/oppose",
        "Breakout filters can reduce trend following robustness.",
    )

    reevaluator = EvidenceConflictReevaluator()
    first = reevaluator.reevaluate(
        topic_key="strategy.breakout.robustness",
        candidates=(support,),
        stances={support.candidate_id: ClaimStance.SUPPORTS},
    )
    second = reevaluator.reevaluate(
        topic_key="strategy.breakout.robustness",
        candidates=(support, oppose),
        stances={
            support.candidate_id: ClaimStance.SUPPORTS,
            oppose.candidate_id: ClaimStance.OPPOSES,
        },
        prior_conflict=first.conflict,
    )
    blocked = reevaluator.reevaluate(
        topic_key="strategy.breakout.robustness",
        candidates=(support,),
        stances={},
    )

    checks = {
        "first_insufficient": first.conflict is not None
        and first.conflict.status is ConflictStatus.INSUFFICIENT_INDEPENDENCE,
        "second_conflict": second.conflict is not None
        and second.conflict.status is ConflictStatus.UNRESOLVED_CONFLICT,
        "status_changed": second.conflict_status_changed,
        "questions_generated": len(second.research_questions) == 1,
        "missing_stance_blocked":
            blocked.status is EvidenceReevaluationStatus.BLOCKED
            and EvidenceReevaluationBlocker.MISSING_STANCE in blocked.blockers,
        "not_validated": not second.knowledge_validated
        and all(not item.knowledge_validated for item in second.positioned_claims),
        "no_auto_resolution": not second.automatic_resolution,
        "no_mutation": not second.strategy_mutated and not second.order_executed,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"evidence conflict reevaluation release check failed: {failed}"
        )

    return {
        "schema_version": EVIDENCE_REEVALUATION_SCHEMA_VERSION,
        "status": second.status.value,
        "conflict_status": second.conflict.status.value,
        "questions": len(second.research_questions),
        "checks": checks,
        "safety": "pass",
    }

