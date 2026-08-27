"""Contracts for Cognitive Core v1.

The models are operational state, not claims of emotion or consciousness.
They deliberately contain no executable code or trading instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CognitiveRecordType(str, Enum):
    GOAL = "goal"
    SELF_MODEL = "self_model"
    REFLECTION = "reflection"
    KNOWLEDGE_GAP = "knowledge_gap"
    PROJECT = "project"
    TOOL = "tool"
    PROACTIVE_IMPROVEMENT = "proactive_improvement"


class GoalStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class CognitiveRecord:
    record_id: str
    record_type: CognitiveRecordType
    namespace: str
    title: str
    status: str
    payload: dict[str, object]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    confidence: float
    verification_state: str
    related_goal: str | None
    created_at: str
    updated_at: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        if not self.record_id or not self.namespace or not self.title:
            raise ValueError("cognitive records require identity, namespace, and title")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if self.verification_state == "verified" and not self.evidence_refs:
            raise ValueError("verified cognitive records require evidence")


@dataclass(frozen=True)
class RetrievedCognitiveContext:
    preferences: tuple[str, ...] = ()
    active_goals: tuple[CognitiveRecord, ...] = ()
    reflections: tuple[CognitiveRecord, ...] = ()
    knowledge_gaps: tuple[CognitiveRecord, ...] = ()
    projects: tuple[CognitiveRecord, ...] = ()
    research_refs: tuple[str, ...] = ()
    budget_used: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        return {
            "preferences": list(self.preferences),
            "active_goal_ids": [item.record_id for item in self.active_goals],
            "reflection_ids": [item.record_id for item in self.reflections],
            "knowledge_gap_ids": [item.record_id for item in self.knowledge_gaps],
            "project_ids": [item.record_id for item in self.projects],
            "research_refs": list(self.research_refs),
            "budget_used": self.budget_used,
            "warnings": list(self.warnings),
        }
