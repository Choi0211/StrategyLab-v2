"""Sprint 179 - External Research Memory.

Stores autonomous external research outcomes as append-only, unvalidated
evidence-backed memory.

Safety invariants:
- memory write is not knowledge validation
- duplicate memory fingerprints are reported, not overwritten
- production approval and policy application remain false
- no strategy mutation, Champion promotion, or trading
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

from gaon.storage.foundation import GaonStorage

from .autonomous_knowledge_loop import KnowledgeResearchLoopResult


EXTERNAL_RESEARCH_MEMORY_SCHEMA_VERSION = 1
MEMORY_FILE = "external_research_memory.jsonl"


class ExternalResearchMemoryStatus(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    BLOCKED = "blocked"


class ExternalResearchMemoryBlocker(str, Enum):
    NO_EVIDENCE = "no_evidence"
    PREVALIDATED_INPUT = "prevalidated_input"


@dataclass(frozen=True)
class ExternalResearchMemoryRecord:
    memory_id: str
    fingerprint: str
    topic_key: str
    loop_id: str
    conflict_status: str | None
    claim_ids: tuple[str, ...]
    question_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    created_at: str
    status: str = "unvalidated_evidence"
    knowledge_validated: bool = False
    production_approved: bool = False
    policy_applied: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_RESEARCH_MEMORY_SCHEMA_VERSION,
            "memory_id": self.memory_id,
            "fingerprint": self.fingerprint,
            "topic_key": self.topic_key,
            "loop_id": self.loop_id,
            "conflict_status": self.conflict_status,
            "claim_ids": list(self.claim_ids),
            "question_ids": list(self.question_ids),
            "source_ids": list(self.source_ids),
            "created_at": self.created_at,
            "status": self.status,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "policy_applied": self.policy_applied,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "ExternalResearchMemoryRecord":
        return cls(
            memory_id=str(payload["memory_id"]),
            fingerprint=str(payload["fingerprint"]),
            topic_key=str(payload["topic_key"]),
            loop_id=str(payload["loop_id"]),
            conflict_status=(
                str(payload["conflict_status"])
                if payload.get("conflict_status") is not None
                else None
            ),
            claim_ids=tuple(str(item) for item in payload.get("claim_ids", ())),
            question_ids=tuple(str(item) for item in payload.get("question_ids", ())),
            source_ids=tuple(str(item) for item in payload.get("source_ids", ())),
            created_at=str(payload["created_at"]),
            status=str(payload.get("status", "unvalidated_evidence")),
            knowledge_validated=bool(payload.get("knowledge_validated", False)),
            production_approved=bool(payload.get("production_approved", False)),
            policy_applied=bool(payload.get("policy_applied", False)),
            strategy_mutated=bool(payload.get("strategy_mutated", False)),
            order_executed=bool(payload.get("order_executed", False)),
        )


@dataclass(frozen=True)
class ExternalResearchMemoryWriteResult:
    status: ExternalResearchMemoryStatus
    record: ExternalResearchMemoryRecord | None
    duplicate_memory_id: str | None
    blockers: tuple[ExternalResearchMemoryBlocker, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "record": self.record.to_json() if self.record else None,
            "duplicate_memory_id": self.duplicate_memory_id,
            "blockers": [item.value for item in self.blockers],
        }


def external_research_memory_fingerprint(loop: KnowledgeResearchLoopResult) -> str:
    encoded = json.dumps(
        {
            "topic_key": loop.topic_key,
            "claim_ids": [candidate.claim_id for candidate in loop.candidates],
            "question_ids": [
                question.question_id
                for question in loop.research_questions
            ],
            "conflict_status": (
                loop.reevaluation.conflict.status.value
                if loop.reevaluation and loop.reevaluation.conflict
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExternalResearchMemoryStore:
    def __init__(self, storage: GaonStorage) -> None:
        self._storage = storage

    @property
    def path(self) -> Path:
        return self._storage.root / "memory" / "research_history" / MEMORY_FILE

    def add_loop_result(
        self,
        loop: KnowledgeResearchLoopResult,
        *,
        created_at: str | None = None,
    ) -> ExternalResearchMemoryWriteResult:
        if not loop.candidates:
            return ExternalResearchMemoryWriteResult(
                ExternalResearchMemoryStatus.BLOCKED,
                None,
                None,
                (ExternalResearchMemoryBlocker.NO_EVIDENCE,),
            )

        if (
            loop.knowledge_validated
            or loop.production_approved
            or loop.strategy_mutated
            or loop.order_executed
        ):
            return ExternalResearchMemoryWriteResult(
                ExternalResearchMemoryStatus.BLOCKED,
                None,
                None,
                (ExternalResearchMemoryBlocker.PREVALIDATED_INPUT,),
            )

        self._storage.initialize()
        fingerprint = external_research_memory_fingerprint(loop)
        existing = self.find_by_fingerprint(fingerprint)
        if existing is not None:
            return ExternalResearchMemoryWriteResult(
                ExternalResearchMemoryStatus.DUPLICATE,
                None,
                existing.memory_id,
                (),
            )

        at = created_at or datetime.now(timezone.utc).isoformat()
        record = ExternalResearchMemoryRecord(
            memory_id=f"external-research-memory:{fingerprint}",
            fingerprint=fingerprint,
            topic_key=loop.topic_key,
            loop_id=loop.loop_id,
            conflict_status=(
                loop.reevaluation.conflict.status.value
                if loop.reevaluation and loop.reevaluation.conflict
                else None
            ),
            claim_ids=tuple(candidate.claim_id for candidate in loop.candidates),
            question_ids=tuple(
                question.question_id
                for question in loop.research_questions
            ),
            source_ids=tuple(
                sorted({candidate.source_id for candidate in loop.candidates})
            ),
            created_at=at,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
        return ExternalResearchMemoryWriteResult(
            ExternalResearchMemoryStatus.STORED,
            record,
            None,
            (),
        )

    def list_records(self) -> tuple[ExternalResearchMemoryRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[ExternalResearchMemoryRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(
                        ExternalResearchMemoryRecord.from_json(json.loads(line))
                    )
        return tuple(records)

    def find_by_fingerprint(
        self,
        fingerprint: str,
    ) -> ExternalResearchMemoryRecord | None:
        for record in self.list_records():
            if record.fingerprint == fingerprint:
                return record
        return None

    def search_by_topic(self, topic_key: str) -> tuple[ExternalResearchMemoryRecord, ...]:
        topic = topic_key.strip().lower()
        return tuple(
            record
            for record in self.list_records()
            if record.topic_key == topic
        )


def external_research_memory_release_check() -> Mapping[str, object]:
    from .autonomous_knowledge_loop import (
        AutonomousKnowledgeResearchLoop,
        SourceEvidenceInput,
    )
    from .conflicts import ClaimStance
    from .provenance import SourceProvenance, SourceType, TrustLevel

    def source(title: str, locator: str, text: str) -> SourceProvenance:
        return SourceProvenance.create(
            source_type=SourceType.ACADEMIC_PAPER,
            title=title,
            locator=locator,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            trust_level=TrustLevel.HIGH,
            author="Researcher",
            publisher="Journal",
            published_at="2026-01-01",
            license_name="test-only",
            ingested_at="2026-08-08T00:00:00+00:00",
        )

    support_text = "Breakout filters can improve trend robustness across regimes."
    oppose_text = "Breakout filters can reduce trend robustness across regimes."
    loop = AutonomousKnowledgeResearchLoop().run(
        topic_key="strategy.breakout.robustness",
        evidence=(
            SourceEvidenceInput(
                source("Support", "https://example.invalid/memory/support", support_text),
                support_text.encode("utf-8"),
                "text/plain",
                ClaimStance.SUPPORTS,
            ),
            SourceEvidenceInput(
                source("Oppose", "https://example.invalid/memory/oppose", oppose_text),
                oppose_text.encode("utf-8"),
                "text/plain",
                ClaimStance.OPPOSES,
            ),
        ),
    )

    with tempfile.TemporaryDirectory() as tmp:
        store = ExternalResearchMemoryStore(GaonStorage(tmp))
        first = store.add_loop_result(loop, created_at="2026-08-08T00:00:00+00:00")
        duplicate = store.add_loop_result(loop, created_at="2026-08-08T00:01:00+00:00")
        records = store.search_by_topic("strategy.breakout.robustness")

    checks = {
        "stored_once": first.status is ExternalResearchMemoryStatus.STORED
        and first.record is not None,
        "duplicate_detected": duplicate.status is ExternalResearchMemoryStatus.DUPLICATE
        and duplicate.duplicate_memory_id == first.record.memory_id,
        "retrievable": len(records) == 1,
        "evidence_backed": len(records[0].claim_ids) == 2
        and len(records[0].source_ids) == 2,
        "not_validated": not records[0].knowledge_validated,
        "not_production": not records[0].production_approved,
        "no_policy": not records[0].policy_applied,
        "no_mutation": not records[0].strategy_mutated
        and not records[0].order_executed,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"external research memory release check failed: {failed}"
        )

    return {
        "schema_version": EXTERNAL_RESEARCH_MEMORY_SCHEMA_VERSION,
        "records": len(records),
        "duplicate": duplicate.status.value,
        "claim_refs": len(records[0].claim_ids),
        "checks": checks,
        "safety": "pass",
    }

