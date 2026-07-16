"""Learning Memory records for Gaon."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from gaon.learning.evidence.models import EvidenceRecord


class LearningMemoryKind(str, Enum):
    """Required Learning Memory categories."""

    RESEARCH_GOAL = "research_goal"
    RESEARCH_PLAN = "research_plan"
    EXPERIMENT = "experiment"
    BACKTEST_RESULT = "backtest_result"
    VALIDATION_RESULT = "validation_result"
    FAILURE_REASON = "failure_reason"
    SUCCESS_PATTERN = "success_pattern"
    USER_PREFERENCE = "user_preference"
    KNOWLEDGE = "knowledge"
    CITATION = "citation"
    CONVERSATION_SUMMARY = "conversation_summary"


@dataclass(frozen=True)
class LearningMemoryRecord:
    """Evidence-backed Learning Memory entry."""

    memory_id: str
    kind: LearningMemoryKind
    content: str
    evidence: tuple[EvidenceRecord, ...]
    version: int = 1

    def __post_init__(self) -> None:
        if not self.memory_id:
            raise ValueError("memory_id is required")
        if not self.content:
            raise ValueError("memory content is required")
        if not self.evidence:
            raise ValueError("learning memory requires evidence")
        if self.version < 1:
            raise ValueError("memory version must be positive")


class LearningMemoryStore:
    """In-memory deterministic store for Sprint 11 tests."""

    def __init__(self) -> None:
        self._records: dict[str, LearningMemoryRecord] = {}

    def add(self, record: LearningMemoryRecord) -> None:
        if record.memory_id in self._records:
            raise ValueError(f"duplicate memory_id: {record.memory_id}")
        self._records[record.memory_id] = record

    def get(self, memory_id: str) -> LearningMemoryRecord:
        try:
            return self._records[memory_id]
        except KeyError as exc:
            raise KeyError(f"unknown memory_id: {memory_id}") from exc

    def by_kind(self, kind: LearningMemoryKind) -> tuple[LearningMemoryRecord, ...]:
        return tuple(record for record in self._records.values() if record.kind is kind)
