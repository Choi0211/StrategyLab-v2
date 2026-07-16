"""Deterministic related-memory retrieval for Sprint 12 runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gaon.learning.contracts import LearningRecord, LearningRecordType
from gaon.learning.detection import normalize_text
from gaon.learning.time import parse_iso8601_utc


@dataclass(frozen=True)
class RelatedMemoryQuery:
    """Input contract for related-memory retrieval."""

    scope: str
    project: str
    strategy: str
    market: str
    query: str
    record_types: tuple[LearningRecordType, ...] = ()
    limit: int | None = None
    reference_time: str | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    """Explainable deterministic retrieval score."""

    scope_match: float
    project_match: float
    strategy_match: float
    market_match: float
    topic_match: float
    validation_state: float
    evidence_quality: float
    recency: float
    conflict_penalty: float
    revalidation_penalty: float
    confidence_signal: float

    @property
    def total(self) -> float:
        return (
            self.scope_match
            + self.project_match
            + self.strategy_match
            + self.market_match
            + self.topic_match
            + self.validation_state
            + self.evidence_quality
            + self.recency
            + self.conflict_penalty
            + self.revalidation_penalty
            + self.confidence_signal
        )


@dataclass(frozen=True)
class RelatedMemoryResult:
    """Ranked retrieval result with warnings and state summaries."""

    record: LearningRecord
    total_score: float
    score_breakdown: ScoreBreakdown
    warnings: tuple[str, ...]
    conflict_state: str
    revalidation_state: str


class RelatedMemoryRetriever:
    """Retrieve related memories without mutating or approving them."""

    def retrieve(self, query: RelatedMemoryQuery, records: tuple[LearningRecord, ...]) -> tuple[RelatedMemoryResult, ...]:
        reference = self._reference_time(query, records)
        results = tuple(self._score(query, record, reference) for record in records if self._eligible(query, record))
        ranked = tuple(sorted(results, key=lambda result: (-result.total_score, result.record.created_at, result.record.record_id)))
        if query.limit is None:
            return ranked
        if query.limit < 1:
            raise ValueError("limit must be positive when provided")
        return ranked[: query.limit]

    def _eligible(self, query: RelatedMemoryQuery, record: LearningRecord) -> bool:
        if query.record_types and record.record_type not in query.record_types:
            return False
        return (
            record.scope == query.scope
            or record.project == query.project
            or record.strategy == query.strategy
            or record.market == query.market
        )

    def _score(self, query: RelatedMemoryQuery, record: LearningRecord, reference_time: datetime) -> RelatedMemoryResult:
        validation_state = record.confidence.validation_state.lower()
        revalidation_due = parse_iso8601_utc(record.revalidation.due_at, "due_at") < reference_time
        warnings: list[str] = []
        if record.confidence.conflict_penalty > 0:
            warnings.append("conflict penalty present")
        if revalidation_due:
            warnings.append("revalidation overdue")
        breakdown = ScoreBreakdown(
            scope_match=3.0 if record.scope == query.scope else 0.0,
            project_match=2.0 if record.project == query.project else 0.0,
            strategy_match=2.0 if record.strategy == query.strategy else 0.0,
            market_match=2.0 if record.market == query.market else 0.0,
            topic_match=1.0 if normalize_text(query.query) in normalize_text(record.content) else 0.0,
            validation_state=self._validation_score(validation_state),
            evidence_quality=min(len(record.evidence), 3) * 0.5,
            recency=self._recency_score(record, reference_time),
            conflict_penalty=-record.confidence.conflict_penalty,
            revalidation_penalty=-1.0 if revalidation_due else 0.0,
            confidence_signal=record.confidence.value,
        )
        return RelatedMemoryResult(
            record=record,
            total_score=breakdown.total,
            score_breakdown=breakdown,
            warnings=tuple(warnings),
            conflict_state="conflict" if record.confidence.conflict_penalty > 0 else "clear",
            revalidation_state="overdue" if revalidation_due else record.revalidation.status.value,
        )

    def _reference_time(self, query: RelatedMemoryQuery, records: tuple[LearningRecord, ...]) -> datetime:
        if query.reference_time is not None:
            return parse_iso8601_utc(query.reference_time, "reference_time")
        if not records:
            raise ValueError("reference_time is required when no records are available")
        return max(parse_iso8601_utc(record.created_at, "created_at") for record in records)

    def _recency_score(self, record: LearningRecord, reference_time: datetime) -> float:
        age_days = max((reference_time - parse_iso8601_utc(record.created_at, "created_at")).days, 0)
        if age_days == 0:
            return 1.0
        if age_days <= 30:
            return 0.75
        if age_days <= 90:
            return 0.25
        return 0.0

    def _validation_score(self, validation_state: str) -> float:
        if validation_state == "validated":
            return 2.0
        if validation_state == "need_validation":
            return 1.0
        if validation_state == "deprecated":
            return -3.0
        return 0.0
