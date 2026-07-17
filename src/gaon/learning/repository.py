"""In-memory Learning Memory repository contracts."""

from __future__ import annotations

from typing import Protocol

from gaon.learning.audit import filter_audit_events
from gaon.learning.contracts import AuditAction, AuditEvent, KnowledgeClaim, LearningRecord, LearningRecordType
from gaon.learning.detection import ConflictCandidate, ConflictDetector, DuplicateCandidate, DuplicateDetector
from gaon.learning.migrations import migrate_repository_json
from gaon.learning.retrieval import RelatedMemoryQuery, RelatedMemoryResult, RelatedMemoryRetriever
from gaon.learning.serialization import repository_from_json, repository_to_json
from gaon.learning.time import parse_iso8601_utc


class LearningRepository(Protocol):
    """Learning Memory repository interface."""

    def add(self, record: LearningRecord) -> None: ...
    def get(self, record_id: str) -> LearningRecord: ...
    def exists(self, record_id: str) -> bool: ...
    def list_all(self) -> tuple[LearningRecord, ...]: ...
    def list_chronological(self) -> tuple[LearningRecord, ...]: ...
    def filter(
        self,
        *,
        scope: str | None = None,
        project: str | None = None,
        strategy: str | None = None,
        market: str | None = None,
        record_type: LearningRecordType | None = None,
    ) -> tuple[LearningRecord, ...]: ...
    def find_duplicates(self, candidate: LearningRecord) -> tuple[DuplicateCandidate, ...]: ...
    def find_conflicts(self, candidate: KnowledgeClaim) -> tuple[ConflictCandidate, ...]: ...
    def list_claims(self) -> tuple[KnowledgeClaim, ...]: ...
    def retrieve_related(self, query: RelatedMemoryQuery) -> tuple[RelatedMemoryResult, ...]: ...
    def append_audit(self, event: AuditEvent) -> None: ...
    def list_audit(self, target_ref: str | None = None, action: AuditAction | None = None) -> tuple[AuditEvent, ...]: ...
    def export_json(self) -> str: ...
    def import_json(self, payload: str) -> None: ...


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
        self._retriever = RelatedMemoryRetriever()

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

    def exists(self, record_id: str) -> bool:
        return record_id in self._records

    def list_all(self) -> tuple[LearningRecord, ...]:
        return tuple(self._copy_record(record) for record in self._records.values())

    def list_chronological(self) -> tuple[LearningRecord, ...]:
        return tuple(sorted(self.list_all(), key=lambda record: (parse_iso8601_utc(record.created_at, "created_at"), record.record_id)))

    def filter(
        self,
        *,
        scope: str | None = None,
        project: str | None = None,
        strategy: str | None = None,
        market: str | None = None,
        record_type: LearningRecordType | None = None,
    ) -> tuple[LearningRecord, ...]:
        records = self.list_chronological()
        if scope is not None:
            records = tuple(record for record in records if record.scope == scope)
        if project is not None:
            records = tuple(record for record in records if record.project == project)
        if strategy is not None:
            records = tuple(record for record in records if record.strategy == strategy)
        if market is not None:
            records = tuple(record for record in records if record.market == market)
        if record_type is not None:
            records = tuple(record for record in records if record.record_type is record_type)
        return records

    def find_duplicates(self, candidate: LearningRecord) -> tuple[DuplicateCandidate, ...]:
        return self._duplicate_detector.find(candidate, self.list_all())

    def find_conflicts(self, candidate: KnowledgeClaim) -> tuple[ConflictCandidate, ...]:
        return self._conflict_detector.find(candidate, tuple(self._copy_claim(claim) for claim in self._claims.values()))

    def list_claims(self) -> tuple[KnowledgeClaim, ...]:
        return tuple(self._copy_claim(claim) for claim in sorted(self._claims.values(), key=lambda claim: claim.claim_id))

    def retrieve_related(self, query: RelatedMemoryQuery) -> tuple[RelatedMemoryResult, ...]:
        return self._retriever.retrieve(query, self.list_all())

    def append_audit(self, event: AuditEvent) -> None:
        if not event.evidence:
            raise ValueError("audit event requires evidence")
        if any(existing.event_id == event.event_id for existing in self._audit_events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._audit_events = (*self._audit_events, self._copy_audit(event))

    def list_audit(self, target_ref: str | None = None, action: AuditAction | None = None) -> tuple[AuditEvent, ...]:
        events = tuple(self._copy_audit(event) for event in self._audit_events)
        return filter_audit_events(events, target_ref=target_ref, action=action)

    def export_json(self) -> str:
        return repository_to_json(self.list_chronological(), self.list_audit(), self.list_claims())

    def import_json(self, payload: str) -> None:
        records, claims, audit_events = repository_from_json(migrate_repository_json(payload))
        if len({record.record_id for record in records}) != len(records):
            raise ValueError("import contains duplicate record_id values")
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise ValueError("import contains duplicate claim_id values")
        if len({event.event_id for event in audit_events}) != len(audit_events):
            raise ValueError("import contains duplicate event_id values")
        imported_records: dict[str, LearningRecord] = {}
        for record in records:
            if not record.evidence:
                raise ValueError("import contains learning record without evidence")
            imported_records[record.record_id] = self._copy_record(record)
        imported_claims: dict[str, KnowledgeClaim] = {}
        for claim in claims:
            if not claim.evidence:
                raise ValueError("import contains knowledge claim without evidence")
            imported_claims[claim.claim_id] = self._copy_claim(claim)
        self._records = imported_records
        self._claims = imported_claims
        self._audit_events = tuple(self._copy_audit(event) for event in filter_audit_events(audit_events))

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
