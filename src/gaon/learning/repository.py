"""In-memory Learning Memory repository contracts."""

from __future__ import annotations

from typing import Protocol

from gaon.learning.contracts import AuditEvent, KnowledgeClaim, LearningRecord
from gaon.learning.detection import ConflictCandidate, ConflictDetector, DuplicateCandidate, DuplicateDetector


class LearningRepository(Protocol):
    """Learning Memory repository interface."""

    def add(self, record: LearningRecord) -> None: ...
    def get(self, record_id: str) -> LearningRecord: ...
    def list_all(self) -> tuple[LearningRecord, ...]: ...
    def list_chronological(self) -> tuple[LearningRecord, ...]: ...
    def filter(self, *, project: str | None = None, strategy: str | None = None, market: str | None = None) -> tuple[LearningRecord, ...]: ...
    def find_duplicates(self, candidate: LearningRecord) -> tuple[DuplicateCandidate, ...]: ...
    def find_conflicts(self, candidate: KnowledgeClaim) -> tuple[ConflictCandidate, ...]: ...
    def append_audit(self, event: AuditEvent) -> None: ...
    def list_audit(self, target_ref: str | None = None) -> tuple[AuditEvent, ...]: ...


class InMemoryLearningRepository:
    """Deterministic in-memory repository for Sprint 12-B tests."""

    def __init__(
        self,
        duplicate_detector: DuplicateDetector | None = None,
        conflict_detector: ConflictDetector | None = None,
    ) -> None:
        self._records: dict[str, LearningRecord] = {}
        self._claims: dict[str, KnowledgeClaim] = {}
        self._audit_events: tuple[AuditEvent, ...] = ()
        self._duplicate_detector = duplicate_detector or DuplicateDetector()
        self._conflict_detector = conflict_detector or ConflictDetector()

    def add(self, record: LearningRecord) -> None:
        if not record.evidence:
            raise ValueError("learning record requires evidence")
        if record.record_id in self._records:
            raise ValueError(f"duplicate record_id: {record.record_id}")
        self._records[record.record_id] = self._copy_record(record)

    def add_claim(self, claim: KnowledgeClaim) -> None:
        if not claim.evidence:
            raise ValueError("knowledge claim requires evidence")
        if claim.claim_id in self._claims:
            raise ValueError(f"duplicate claim_id: {claim.claim_id}")
        self._claims[claim.claim_id] = self._copy_claim(claim)

    def get(self, record_id: str) -> LearningRecord:
        try:
            return self._copy_record(self._records[record_id])
        except KeyError as exc:
            raise KeyError(f"unknown record_id: {record_id}") from exc

    def list_all(self) -> tuple[LearningRecord, ...]:
        return tuple(self._copy_record(record) for record in self._records.values())

    def list_chronological(self) -> tuple[LearningRecord, ...]:
        return tuple(sorted(self.list_all(), key=lambda record: (record.created_at, record.record_id)))

    def filter(
        self,
        *,
        project: str | None = None,
        strategy: str | None = None,
        market: str | None = None,
    ) -> tuple[LearningRecord, ...]:
        records = self.list_chronological()
        if project is not None:
            records = tuple(record for record in records if record.project == project)
        if strategy is not None:
            records = tuple(record for record in records if record.strategy == strategy)
        if market is not None:
            records = tuple(record for record in records if record.market == market)
        return records

    def find_duplicates(self, candidate: LearningRecord) -> tuple[DuplicateCandidate, ...]:
        return self._duplicate_detector.find(candidate, self.list_all())

    def find_conflicts(self, candidate: KnowledgeClaim) -> tuple[ConflictCandidate, ...]:
        return self._conflict_detector.find(candidate, tuple(self._copy_claim(claim) for claim in self._claims.values()))

    def append_audit(self, event: AuditEvent) -> None:
        if not event.evidence:
            raise ValueError("audit event requires evidence")
        if any(existing.event_id == event.event_id for existing in self._audit_events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._audit_events = (*self._audit_events, self._copy_audit(event))

    def list_audit(self, target_ref: str | None = None) -> tuple[AuditEvent, ...]:
        events = tuple(self._copy_audit(event) for event in self._audit_events)
        if target_ref is not None:
            events = tuple(event for event in events if event.target_ref == target_ref)
        return events

    def replace_audit(self, event: AuditEvent) -> None:
        raise PermissionError("audit events are append-only")

    def delete_audit(self, event_id: str) -> None:
        raise PermissionError("audit events are append-only")

    @staticmethod
    def _copy_record(record: LearningRecord) -> LearningRecord:
        return LearningRecord.from_json(record.to_json())

    @staticmethod
    def _copy_claim(claim: KnowledgeClaim) -> KnowledgeClaim:
        return KnowledgeClaim.from_json(claim.to_json())

    @staticmethod
    def _copy_audit(event: AuditEvent) -> AuditEvent:
        return AuditEvent.from_json(event.to_json())
