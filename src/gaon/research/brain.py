"""Research Brain contracts for Sprint 11."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from gaon.learning.evidence.models import EvidenceRecord, EvidenceType
from gaon.learning.memory.models import LearningMemoryKind, LearningMemoryRecord

RESEARCH_BRAIN_SCHEMA_VERSION = 1


def _require_evidence(evidence: tuple[EvidenceRecord, ...], owner: str) -> None:
    if not evidence:
        raise ValueError(f"{owner} requires evidence")


def _require_nonempty_tuple(values: tuple[str, ...], owner: str) -> None:
    if not values:
        raise ValueError(f"{owner} requires at least one item")
    if any(not value for value in values):
        raise ValueError(f"{owner} items must not be empty")


def _evidence_to_dict(record: EvidenceRecord) -> dict[str, str]:
    return {
        "evidence_id": record.evidence_id,
        "evidence_type": record.evidence_type.value,
        "reference": record.reference,
        "summary": record.summary,
    }


def _evidence_from_dict(data: dict[str, str]) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=data["evidence_id"],
        evidence_type=EvidenceType(data["evidence_type"]),
        reference=data["reference"],
        summary=data["summary"],
    )


def _versioned_payload(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_BRAIN_SCHEMA_VERSION,
        "kind": kind,
        "data": data,
    }


def _load_versioned_json(payload: str, expected_kind: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    if decoded.get("schema_version") != RESEARCH_BRAIN_SCHEMA_VERSION:
        raise ValueError("unsupported Research Brain schema version")
    if decoded.get("kind") != expected_kind:
        raise ValueError(f"expected {expected_kind} payload")
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise ValueError("versioned payload data must be an object")
    return data


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

    def to_json(self) -> str:
        return json.dumps(
            _versioned_payload(
                "research_goal",
                {
                    "goal_id": self.goal_id,
                    "question": self.question,
                    "scope": self.scope,
                    "success_criteria": list(self.success_criteria),
                    "evidence": [_evidence_to_dict(record) for record in self.evidence],
                },
            ),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchGoal":
        data = _load_versioned_json(payload, "research_goal")
        return cls(
            goal_id=data["goal_id"],
            question=data["question"],
            scope=data["scope"],
            success_criteria=tuple(data["success_criteria"]),
            evidence=tuple(_evidence_from_dict(record) for record in data["evidence"]),
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

    def to_json(self) -> str:
        return json.dumps(
            _versioned_payload(
                "research_plan",
                {
                    "plan_id": self.plan_id,
                    "goal_id": self.goal_id,
                    "steps": list(self.steps),
                    "constraints": list(self.constraints),
                    "evidence": [_evidence_to_dict(record) for record in self.evidence],
                },
            ),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchPlan":
        data = _load_versioned_json(payload, "research_plan")
        return cls(
            plan_id=data["plan_id"],
            goal_id=data["goal_id"],
            steps=tuple(data["steps"]),
            constraints=tuple(data["constraints"]),
            evidence=tuple(_evidence_from_dict(record) for record in data["evidence"]),
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


_SESSION_TRANSITIONS: dict[ResearchSessionStatus, tuple[ResearchSessionStatus, ...]] = {
    ResearchSessionStatus.PLANNED: (ResearchSessionStatus.RUNNING, ResearchSessionStatus.BLOCKED),
    ResearchSessionStatus.RUNNING: (ResearchSessionStatus.COMPLETED, ResearchSessionStatus.BLOCKED),
    ResearchSessionStatus.BLOCKED: (ResearchSessionStatus.RUNNING,),
    ResearchSessionStatus.COMPLETED: (),
}


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
        if status not in _SESSION_TRANSITIONS[self.status]:
            raise ValueError(f"invalid research session transition: {self.status.value} -> {status.value}")
        notes = self.notes
        if note is not None:
            if not note:
                raise ValueError("transition note must not be empty")
            notes = (*notes, note)
        return replace(self, status=status, notes=notes)

    def to_json(self) -> str:
        return json.dumps(
            _versioned_payload(
                "research_session",
                {
                    "session_id": self.session_id,
                    "goal": json.loads(self.goal.to_json()),
                    "plan": json.loads(self.plan.to_json()),
                    "status": self.status.value,
                    "evidence": [_evidence_to_dict(record) for record in self.evidence],
                    "notes": list(self.notes),
                },
            ),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchSession":
        data = _load_versioned_json(payload, "research_session")
        return cls(
            session_id=data["session_id"],
            goal=ResearchGoal.from_json(json.dumps(data["goal"])),
            plan=ResearchPlan.from_json(json.dumps(data["plan"])),
            status=ResearchSessionStatus(data["status"]),
            evidence=tuple(_evidence_from_dict(record) for record in data["evidence"]),
            notes=tuple(data["notes"]),
        )


@dataclass(frozen=True)
class ResearchInterview:
    """Structured interview used to clarify a research goal."""

    interview_id: str
    goal_id: str
    questions: tuple[str, ...]
    answers: tuple[str | None, ...]
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.interview_id:
            raise ValueError("interview_id is required")
        if not self.goal_id:
            raise ValueError("goal_id is required")
        _require_nonempty_tuple(self.questions, "questions")
        if len(self.questions) != len(self.answers):
            raise ValueError("questions and answers must have the same length")
        if any(answer == "" for answer in self.answers):
            raise ValueError("answers must use None for pending responses")
        _require_evidence(self.evidence, "research interview")

    @property
    def pending_questions(self) -> tuple[str, ...]:
        return tuple(question for question, answer in zip(self.questions, self.answers) if answer is None)

    @property
    def is_complete(self) -> bool:
        return not self.pending_questions

    def to_json(self) -> str:
        return json.dumps(
            _versioned_payload(
                "research_interview",
                {
                    "interview_id": self.interview_id,
                    "goal_id": self.goal_id,
                    "questions": list(self.questions),
                    "answers": list(self.answers),
                    "evidence": [_evidence_to_dict(record) for record in self.evidence],
                },
            ),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchInterview":
        data = _load_versioned_json(payload, "research_interview")
        return cls(
            interview_id=data["interview_id"],
            goal_id=data["goal_id"],
            questions=tuple(data["questions"]),
            answers=tuple(data["answers"]),
            evidence=tuple(_evidence_from_dict(record) for record in data["evidence"]),
        )


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type.value,
            "content": self.content,
            "evidence": [_evidence_to_dict(record) for record in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchJournalEntry":
        return cls(
            entry_id=data["entry_id"],
            entry_type=ResearchJournalEntryType(data["entry_type"]),
            content=data["content"],
            evidence=tuple(_evidence_from_dict(record) for record in data["evidence"]),
        )


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

    def to_json(self) -> str:
        return json.dumps(
            _versioned_payload(
                "research_journal",
                {
                    "journal_id": self.journal_id,
                    "session_id": self.session_id,
                    "entries": [entry.to_dict() for entry in self.entries],
                },
            ),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchJournal":
        data = _load_versioned_json(payload, "research_journal")
        return cls(
            journal_id=data["journal_id"],
            session_id=data["session_id"],
            entries=tuple(ResearchJournalEntry.from_dict(entry) for entry in data["entries"]),
        )
