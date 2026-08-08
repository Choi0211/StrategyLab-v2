"""Sprint 170 — Knowledge Gap & Research Question Generation.

Turns unresolved knowledge states into bounded, structured research questions.

Safety invariants:
- gaps are generated only from structured prior evidence state
- no free-form fabricated facts
- research questions are not answers
- queue entries are not instructions to mutate strategy
- no automatic knowledge validation
- no Champion promotion
- no KIS/Broker/live order execution
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping

from .conflicts import (
    ConflictStatus,
    KnowledgeConflictRecord,
)


GAP_SCHEMA_VERSION = 1

_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")


class KnowledgeGapType(str, Enum):
    CONTRADICTION = "contradiction"
    INSUFFICIENT_INDEPENDENCE = "insufficient_independence"
    MISSING_DIRECTIONAL_EVIDENCE = "missing_directional_evidence"


class ResearchPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RequiredEvidenceType(str, Enum):
    INDEPENDENT_PRIMARY_SOURCE = "independent_primary_source"
    INDEPENDENT_SUPPORTING_SOURCE = "independent_supporting_source"
    OPPOSING_EVIDENCE = "opposing_evidence"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    COMPARABLE_DIRECTIONAL_EVIDENCE = "comparable_directional_evidence"
    MARKET_REGIME_EVIDENCE = "market_regime_evidence"
    DATASET_EVIDENCE = "dataset_evidence"


class ResearchStopCondition(str, Enum):
    TWO_INDEPENDENT_PRIMARY_SOURCES = "two_independent_primary_sources"
    OPPOSING_EVIDENCE_RESOLVED = "opposing_evidence_resolved"
    COMPARABLE_EVIDENCE_ACQUIRED = "comparable_evidence_acquired"
    EVIDENCE_BUDGET_EXHAUSTED = "evidence_budget_exhausted"


@dataclass(frozen=True)
class RequiredEvidence:
    evidence_type: RequiredEvidenceType
    minimum_independent_sources: int
    rationale: str

    def __post_init__(self) -> None:
        if self.minimum_independent_sources <= 0:
            raise ValueError(
                "minimum_independent_sources must be positive"
            )
        if not self.rationale.strip():
            raise ValueError("required evidence rationale is required")

    def to_json(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type.value,
            "minimum_independent_sources":
                self.minimum_independent_sources,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ResearchQuestion:
    question_id: str
    topic_key: str
    gap_type: KnowledgeGapType
    question: str
    priority: ResearchPriority
    required_evidence: tuple[RequiredEvidence, ...]
    stop_conditions: tuple[ResearchStopCondition, ...]
    parent_conflict_id: str
    source_state: ConflictStatus
    knowledge_validated: bool = False
    production_approved: bool = False
    policy_applied: bool = False
    execution_authorized: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": GAP_SCHEMA_VERSION,
            "question_id": self.question_id,
            "topic_key": self.topic_key,
            "gap_type": self.gap_type.value,
            "question": self.question,
            "priority": self.priority.value,
            "required_evidence": [
                item.to_json()
                for item in self.required_evidence
            ],
            "stop_conditions": [
                item.value
                for item in self.stop_conditions
            ],
            "parent_conflict_id": self.parent_conflict_id,
            "source_state": self.source_state.value,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "policy_applied": self.policy_applied,
            "execution_authorized": self.execution_authorized,
        }


def canonical_question_id(
    *,
    topic_key: str,
    gap_type: KnowledgeGapType,
    parent_conflict_id: str,
) -> str:
    topic = topic_key.strip().lower()

    if not _TOPIC_RE.fullmatch(topic):
        raise ValueError("invalid topic_key")

    if not parent_conflict_id.startswith("knowledge-conflict:"):
        raise ValueError("invalid parent_conflict_id")

    encoded = json.dumps(
        {
            "topic_key": topic,
            "gap_type": gap_type.value,
            "parent_conflict_id": parent_conflict_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"research-question:{hashlib.sha256(encoded).hexdigest()}"


class KnowledgeGapDetector:
    """Maps structured conflict states to explicit research gaps."""

    def detect(
        self,
        conflict: KnowledgeConflictRecord,
    ) -> KnowledgeGapType | None:
        if conflict.status is ConflictStatus.UNRESOLVED_CONFLICT:
            return KnowledgeGapType.CONTRADICTION

        if conflict.status is ConflictStatus.INSUFFICIENT_INDEPENDENCE:
            return KnowledgeGapType.INSUFFICIENT_INDEPENDENCE

        if conflict.status is ConflictStatus.NO_COMPARABLE_EVIDENCE:
            return KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE

        if conflict.status is ConflictStatus.SUPPORTED:
            return None

        raise ValueError(
            f"unsupported conflict status: {conflict.status}"
        )


class ResearchQuestionGenerator:
    """Deterministically converts a knowledge gap to a research question."""

    def __init__(
        self,
        *,
        max_questions_per_conflict: int = 1,
    ) -> None:
        if max_questions_per_conflict <= 0:
            raise ValueError(
                "max_questions_per_conflict must be positive"
            )

        # Sprint 170 intentionally emits one canonical question per gap.
        self.max_questions_per_conflict = max_questions_per_conflict

    def generate(
        self,
        conflict: KnowledgeConflictRecord,
    ) -> tuple[ResearchQuestion, ...]:
        gap_type = KnowledgeGapDetector().detect(conflict)

        if gap_type is None:
            return ()

        question = self._build_question(
            conflict=conflict,
            gap_type=gap_type,
        )

        return (question,)[: self.max_questions_per_conflict]

    def _build_question(
        self,
        *,
        conflict: KnowledgeConflictRecord,
        gap_type: KnowledgeGapType,
    ) -> ResearchQuestion:
        topic = conflict.topic_key

        if gap_type is KnowledgeGapType.CONTRADICTION:
            text = (
                f"What independent evidence can explain or resolve the "
                f"opposing claims for research topic '{topic}'?"
            )

            required = (
                RequiredEvidence(
                    evidence_type=
                        RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                    minimum_independent_sources=2,
                    rationale=(
                        "Conflicting claims require independent primary "
                        "evidence before any resolution."
                    ),
                ),
                RequiredEvidence(
                    evidence_type=
                        RequiredEvidenceType.MARKET_REGIME_EVIDENCE,
                    minimum_independent_sources=1,
                    rationale=(
                        "Different regimes or conditions may explain why "
                        "credible sources disagree."
                    ),
                ),
            )

            stop_conditions = (
                ResearchStopCondition.OPPOSING_EVIDENCE_RESOLVED,
                ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,
            )

            priority = ResearchPriority.HIGH

        elif gap_type is KnowledgeGapType.INSUFFICIENT_INDEPENDENCE:
            text = (
                f"What independent source can corroborate or challenge the "
                f"existing evidence for research topic '{topic}'?"
            )

            required = (
                RequiredEvidence(
                    evidence_type=
                        RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                    minimum_independent_sources=1,
                    rationale=(
                        "Existing directional evidence lacks sufficient "
                        "source independence."
                    ),
                ),
            )

            stop_conditions = (
                ResearchStopCondition.TWO_INDEPENDENT_PRIMARY_SOURCES,
                ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,
            )

            priority = ResearchPriority.MEDIUM

        elif gap_type is KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE:
            text = (
                f"What directional evidence exists for research topic "
                f"'{topic}'?"
            )

            required = (
                RequiredEvidence(
                    evidence_type=
                        RequiredEvidenceType.COMPARABLE_DIRECTIONAL_EVIDENCE,
                    minimum_independent_sources=1,
                    rationale=(
                        "The topic currently has no comparable directional "
                        "evidence."
                    ),
                ),
            )

            stop_conditions = (
                ResearchStopCondition.COMPARABLE_EVIDENCE_ACQUIRED,
                ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,
            )

            priority = ResearchPriority.MEDIUM

        else:
            raise ValueError(f"unsupported gap_type: {gap_type}")

        return ResearchQuestion(
            question_id=canonical_question_id(
                topic_key=topic,
                gap_type=gap_type,
                parent_conflict_id=conflict.conflict_id,
            ),
            topic_key=topic,
            gap_type=gap_type,
            question=text,
            priority=priority,
            required_evidence=required,
            stop_conditions=stop_conditions,
            parent_conflict_id=conflict.conflict_id,
            source_state=conflict.status,
        )


@dataclass(frozen=True)
class ResearchQueueEntry:
    queue_id: str
    question: ResearchQuestion
    sequence: int
    attempts: int
    max_attempts: int
    status: str
    auto_execute: bool = False

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.attempts < 0:
            raise ValueError("attempts must be non-negative")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.attempts > self.max_attempts:
            raise ValueError("attempts exceed max_attempts")

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": GAP_SCHEMA_VERSION,
            "queue_id": self.queue_id,
            "question": self.question.to_json(),
            "sequence": self.sequence,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "status": self.status,
            "auto_execute": self.auto_execute,
        }


def canonical_queue_id(question_id: str) -> str:
    if not question_id.startswith("research-question:"):
        raise ValueError("invalid question_id")

    digest = hashlib.sha256(
        question_id.encode("utf-8")
    ).hexdigest()

    return f"research-queue:{digest}"


class AutonomousResearchQueueBuilder:
    """Builds a bounded queue contract without executing research."""

    def __init__(
        self,
        *,
        default_max_attempts: int = 3,
    ) -> None:
        if default_max_attempts <= 0:
            raise ValueError(
                "default_max_attempts must be positive"
            )
        self.default_max_attempts = default_max_attempts

    def build(
        self,
        questions: Iterable[ResearchQuestion],
    ) -> tuple[ResearchQueueEntry, ...]:
        unique: dict[str, ResearchQuestion] = {}

        for question in questions:
            unique.setdefault(
                question.question_id,
                question,
            )

        ordered = sorted(
            unique.values(),
            key=lambda item: (
                self._priority_rank(item.priority),
                item.question_id,
            ),
        )

        return tuple(
            ResearchQueueEntry(
                queue_id=canonical_queue_id(
                    question.question_id
                ),
                question=question,
                sequence=index,
                attempts=0,
                max_attempts=self.default_max_attempts,
                status="pending",
                auto_execute=False,
            )
            for index, question in enumerate(ordered)
        )

    @staticmethod
    def _priority_rank(
        priority: ResearchPriority,
    ) -> int:
        return {
            ResearchPriority.HIGH: 0,
            ResearchPriority.MEDIUM: 1,
            ResearchPriority.LOW: 2,
        }[priority]


def gap_release_check() -> Mapping[str, object]:
    from .conflicts import KnowledgeConflictRecord

    conflict = KnowledgeConflictRecord(
        conflict_id="knowledge-conflict:test",
        topic_key="trend.regime.robustness",
        status=ConflictStatus.UNRESOLVED_CONFLICT,
        supporting_claim_ids=("claim:a",),
        opposing_claim_ids=("claim:b",),
        neutral_claim_ids=(),
        independent_source_count=2,
        supporting_source_count=1,
        opposing_source_count=1,
        supporting_score=90,
        opposing_score=85,
        reasons=(
            "independent_sources_support_opposing_stances",
        ),
    )

    questions = ResearchQuestionGenerator().generate(
        conflict
    )

    queue = AutonomousResearchQueueBuilder().build(
        questions
    )

    checks = {
        "gap_detected":
            len(questions) == 1
            and questions[0].gap_type
            is KnowledgeGapType.CONTRADICTION,
        "question_is_grounded":
            questions[0].parent_conflict_id
            == conflict.conflict_id,
        "high_priority":
            questions[0].priority
            is ResearchPriority.HIGH,
        "required_evidence_present":
            len(questions[0].required_evidence) >= 1,
        "stop_condition_present":
            len(questions[0].stop_conditions) >= 1,
        "queue_created": len(queue) == 1,
        "queue_bounded": queue[0].max_attempts == 3,
        "no_auto_execute": queue[0].auto_execute is False,
        "not_validated":
            questions[0].knowledge_validated is False,
        "not_production":
            questions[0].production_approved is False,
        "policy_not_applied":
            questions[0].policy_applied is False,
        "execution_not_authorized":
            questions[0].execution_authorized is False,
    }

    if not all(checks.values()):
        failed = ",".join(
            name
            for name, ok in checks.items()
            if not ok
        )
        raise RuntimeError(
            f"knowledge gap release check failed: {failed}"
        )

    return {
        "schema_version": GAP_SCHEMA_VERSION,
        "gap_type": questions[0].gap_type.value,
        "priority": questions[0].priority.value,
        "questions": len(questions),
        "queue_entries": len(queue),
        "max_attempts": queue[0].max_attempts,
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = gap_release_check()

    print(
        "gaon-knowledge-gap-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"gap={payload['gap_type']} "
        f"priority={payload['priority']} "
        f"questions={payload['questions']} "
        f"queue_entries={payload['queue_entries']} "
        f"max_attempts={payload['max_attempts']} "
        "auto_execute=false "
        "knowledge_validated=false "
        "production_approved=false "
        "policy_applied=false "
        "execution_authorized=false "
        "safety=pass"
    )
