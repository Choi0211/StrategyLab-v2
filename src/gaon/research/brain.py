"""Research Brain contracts for Sprint 11."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from gaon.learning.evidence.models import EvidenceRecord
from gaon.learning.memory.models import LearningMemoryKind, LearningMemoryRecord


def _require_evidence(evidence: tuple[EvidenceRecord, ...], owner: str) -> None:
    if not evidence:
        raise ValueError(f"{owner} requires evidence")


def _require_nonempty_tuple(values: tuple[str, ...], owner: str) -> None:
    if not values:
        raise ValueError(f"{owner} requires at least one item")
    if any(not value for value in values):
        raise ValueError(f"{owner} items must not be empty")


@dataclass(frozen=True)
class ResearchGoal:
    """Evidence-backed research goal."""

    goal_id: str
    question: str
    scope: str
    success_criteria: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.goal_id:
            raise ValueError("goal_id is required")
        if not self.question:
            raise ValueError("question is required")
        if not self.scope:
            raise ValueError("scope is required")
        _require_nonempty_tuple(self.success_criteria, "success_criteria")
        _require_evidence(self.evidence, "research goal")

    def to_memory_record(self) -> LearningMemoryRecord:
        return LearningMemoryRecord(
            memory_id=f"memory:{self.goal_id}",
            kind=LearningMemoryKind.RESEARCH_GOAL,
            content=f"{self.question} | scope={self.scope}",
            evidence=self.evidence,
        )


@dataclass(frozen=True)
class ResearchPlan:
    """Deterministic plan for a research goal."""

    plan_id: str
    goal_id: str
    steps: tuple[str, ...]
    constraints: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan_id is required")
        if not self.goal_id:
            raise ValueError("goal_id is required")
        _require_nonempty_tuple(self.steps, "steps")
        _require_evidence(self.evidence, "research plan")
        if any(not constraint for constraint in self.constraints):
            raise ValueError("constraints must not contain empty values")

    def to_memory_record(self) -> LearningMemoryRecord:
        return LearningMemoryRecord(
            memory_id=f"memory:{self.plan_id}",
            kind=LearningMemoryKind.RESEARCH_PLAN,
            content=" -> ".join(self.steps),
            evidence=self.evidence,
        )


def build_research_plan(
    goal: ResearchGoal,
    *,
    plan_id: str,
    steps: tuple[str, ...],
    constraints: tuple[str, ...] = (),
) -> ResearchPlan:
    """Build a deterministic research plan from a goal."""

    return ResearchPlan(
        plan_id=plan_id,
        goal_id=goal.goal_id,
        steps=steps,
        constraints=constraints,
        evidence=goal.evidence,
    )


class ResearchSessionStatus(str, Enum):
    """Research session lifecycle."""

    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ResearchSession:
    """Research session connecting a goal and a plan."""

    session_id: str
    goal: ResearchGoal
    plan: ResearchPlan
    status: ResearchSessionStatus
    evidence: tuple[EvidenceRecord, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.plan.goal_id != self.goal.goal_id:
            raise ValueError("plan goal_id must match research goal")
        _require_evidence(self.evidence, "research session")
        if any(not note for note in self.notes):
            raise ValueError("notes must not contain empty values")

    def transition(self, status: ResearchSessionStatus, *, note: str | None = None) -> "ResearchSession":
        notes = self.notes
        if note is not None:
            if not note:
                raise ValueError("transition note must not be empty")
            notes = (*notes, note)
        return replace(self, status=status, notes=notes)


@dataclass(frozen=True)
class ResearchInterview:
    """Structured interview used to clarify a research goal."""

    interview_id: str
    goal_id: str
    questions: tuple[str, ...]
    answers: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.interview_id:
            raise ValueError("interview_id is required")
        if not self.goal_id:
            raise ValueError("goal_id is required")
        _require_nonempty_tuple(self.questions, "questions")
        _require_nonempty_tuple(self.answers, "answers")
        if len(self.questions) != len(self.answers):
            raise ValueError("questions and answers must have the same length")
        _require_evidence(self.evidence, "research interview")


class ResearchJournalEntryType(str, Enum):
    """Research journal entry category."""

    OBSERVATION = "observation"
    DECISION = "decision"
    NEXT_ACTION = "next_action"


@dataclass(frozen=True)
class ResearchJournalEntry:
    """Single evidence-backed research journal entry."""

    entry_id: str
    entry_type: ResearchJournalEntryType
    content: str
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id is required")
        if not self.content:
            raise ValueError("content is required")
        _require_evidence(self.evidence, "research journal entry")


@dataclass(frozen=True)
class ResearchJournal:
    """Immutable research journal for a session."""

    journal_id: str
    session_id: str
    entries: tuple[ResearchJournalEntry, ...]

    def __post_init__(self) -> None:
        if not self.journal_id:
            raise ValueError("journal_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")

    def add_entry(self, entry: ResearchJournalEntry) -> "ResearchJournal":
        if any(existing.entry_id == entry.entry_id for existing in self.entries):
            raise ValueError(f"duplicate journal entry: {entry.entry_id}")
        return replace(self, entries=(*self.entries, entry))
