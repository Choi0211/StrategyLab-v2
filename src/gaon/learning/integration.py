"""Research Brain to Learning Memory integration workflow."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.learning.confidence.models import ConfidenceScore
from gaon.learning.contracts import (
    LearningRecord,
    LearningRecordType,
    ResearchOutcome,
    RevalidationSchedule,
    RevalidationStatus,
)
from gaon.learning.detection import ConflictCandidate, DuplicateCandidate
from gaon.learning.repository import LearningRepository
from gaon.research.brain import ResearchGoal, ResearchJournalEntry, ResearchPlan, ResearchSession, ResearchSessionStatus


@dataclass(frozen=True)
class PreparedMemory:
    """Research-memory preparation result without automatic persistence."""

    proposed_records: tuple[LearningRecord, ...]
    duplicate_candidates: tuple[DuplicateCandidate, ...]
    conflict_candidates: tuple[ConflictCandidate, ...]


def research_goal_to_record(
    goal: ResearchGoal,
    *,
    project: str,
    strategy: str,
    market: str,
    created_at: str,
) -> LearningRecord:
    return _record(
        record_id=f"research-goal:{goal.goal_id}",
        record_type=LearningRecordType.RESEARCH_OUTCOME,
        content=goal.question,
        scope=goal.scope,
        project=project,
        strategy=strategy,
        market=market,
        created_at=created_at,
        evidence=goal.evidence,
        audit_ref=f"audit:research-goal:{goal.goal_id}",
    )


def research_plan_to_record(
    plan: ResearchPlan,
    *,
    scope: str,
    project: str,
    strategy: str,
    market: str,
    created_at: str,
) -> LearningRecord:
    return _record(
        record_id=f"research-plan:{plan.plan_id}",
        record_type=LearningRecordType.RESEARCH_OUTCOME,
        content=" -> ".join(plan.steps),
        scope=scope,
        project=project,
        strategy=strategy,
        market=market,
        created_at=created_at,
        evidence=plan.evidence,
        audit_ref=f"audit:research-plan:{plan.plan_id}",
    )


def research_session_to_outcome(
    session: ResearchSession,
    *,
    project: str,
    strategy: str,
    market: str,
) -> ResearchOutcome:
    if session.status is not ResearchSessionStatus.COMPLETED:
        raise ValueError("research session must be completed before outcome conversion")
    return ResearchOutcome(
        outcome_id=f"research-outcome:{session.session_id}",
        research_goal_id=session.goal.goal_id,
        experiment_id=session.plan.plan_id,
        result_summary=" | ".join(session.notes) if session.notes else "completed research session",
        metrics={"notes": float(len(session.notes))},
        conclusion=session.notes[-1] if session.notes else "needs validation",
        scope=session.goal.scope,
        project=project,
        strategy=strategy,
        market=market,
        evidence=session.evidence,
        confidence=_confidence(),
    )


def research_journal_entry_to_record(
    entry: ResearchJournalEntry,
    *,
    session_id: str,
    scope: str,
    project: str,
    strategy: str,
    market: str,
    created_at: str,
) -> LearningRecord:
    return _record(
        record_id=f"research-journal:{session_id}:{entry.entry_id}",
        record_type=LearningRecordType.CONVERSATION_SUMMARY,
        content=entry.content,
        scope=scope,
        project=project,
        strategy=strategy,
        market=market,
        created_at=created_at,
        evidence=entry.evidence,
        audit_ref=f"audit:research-journal:{session_id}:{entry.entry_id}",
    )


def prepare_memory(repository: LearningRepository, records: tuple[LearningRecord, ...]) -> PreparedMemory:
    """Prepare memory candidates and detector output without saving."""

    duplicates: list[DuplicateCandidate] = []
    for record in records:
        duplicates.extend(repository.find_duplicates(record))
    return PreparedMemory(
        proposed_records=records,
        duplicate_candidates=tuple(duplicates),
        conflict_candidates=(),
    )


def _record(
    *,
    record_id: str,
    record_type: LearningRecordType,
    content: str,
    scope: str,
    project: str,
    strategy: str,
    market: str,
    created_at: str,
    evidence: tuple,
    audit_ref: str,
) -> LearningRecord:
    return LearningRecord(
        record_id=record_id,
        record_type=record_type,
        content=content,
        scope=scope,
        project=project,
        strategy=strategy,
        market=market,
        created_at=created_at,
        updated_at=created_at,
        version=1,
        evidence=evidence,
        confidence=_confidence(),
        revalidation=RevalidationSchedule(
            schedule_id=f"revalidation:{record_id}",
            target_ref=record_id,
            reason="research memory scheduled validation",
            due_at="2026-08-01T00:00:00Z",
            frequency="monthly",
            status=RevalidationStatus.PENDING,
            scope=scope,
            project=project,
            strategy=strategy,
            market=market,
        ),
        audit_ref=audit_ref,
    )


def _confidence() -> ConfidenceScore:
    return ConfidenceScore(
        value=0.5,
        reason="research brain conversion candidate",
        evidence_count=1,
        validation_state="need_validation",
        recency=1.0,
        conflict_penalty=0.0,
    )
