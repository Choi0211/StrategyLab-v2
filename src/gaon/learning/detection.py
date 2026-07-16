"""Duplicate and conflict detection contracts for Learning Memory."""

from __future__ import annotations

from dataclasses import dataclass
import re
import string

from gaon.learning.contracts import KnowledgeClaim, LearningRecord
from gaon.learning.knowledge.models import KnowledgeStatus


def normalize_text(value: str) -> str:
    """Normalize text for deterministic candidate detection."""

    cleaned = value.strip().lower().translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", cleaned)


def _same_scope(left: LearningRecord | KnowledgeClaim, right: LearningRecord | KnowledgeClaim) -> bool:
    return (
        left.scope == right.scope
        and left.project == right.project
        and left.strategy == right.strategy
        and left.market == right.market
    )


def _evidence_refs(record: LearningRecord | KnowledgeClaim) -> set[str]:
    return {evidence.reference for evidence in record.evidence}


@dataclass(frozen=True)
class DuplicateCandidate:
    """Potential duplicate record without automatic merge."""

    candidate_id: str
    matched_record_ids: tuple[str, ...]
    reason: str
    similarity_basis: tuple[str, ...]
    requires_review: bool = True

    @property
    def existing_id(self) -> str:
        return self.matched_record_ids[0]


@dataclass(frozen=True)
class ConflictCandidate:
    """Potential conflict without automatic resolution."""

    candidate_id: str
    conflicting_record_ids: tuple[str, ...]
    reason: str
    requires_validation: bool = True

    @property
    def existing_id(self) -> str:
        return self.conflicting_record_ids[0]


class DuplicateDetector:
    """Detect duplicate candidates deterministically."""

    def find(self, candidate: LearningRecord, records: tuple[LearningRecord, ...]) -> tuple[DuplicateCandidate, ...]:
        candidates: list[DuplicateCandidate] = []
        candidate_text = normalize_text(candidate.content)
        candidate_refs = _evidence_refs(candidate)
        for record in records:
            if record.record_id == candidate.record_id:
                continue
            if not _same_scope(record, candidate):
                continue
            record_refs = _evidence_refs(record)
            compatible_type = record.record_type == candidate.record_type
            if normalize_text(record.content) == candidate_text and candidate_refs.intersection(record_refs) and compatible_type:
                candidates.append(
                    DuplicateCandidate(
                        candidate_id=candidate.record_id,
                        matched_record_ids=(record.record_id,),
                        reason="matching content, scope, record type, and evidence reference",
                        similarity_basis=("normalized_content", "scope", "record_type", "evidence_reference"),
                    )
                )
        return tuple(candidates)


class ConflictDetector:
    """Detect incompatible knowledge claims deterministically."""

    def find(self, candidate: KnowledgeClaim, claims: tuple[KnowledgeClaim, ...]) -> tuple[ConflictCandidate, ...]:
        candidates: list[ConflictCandidate] = []
        candidate_text = normalize_text(candidate.statement)
        for claim in claims:
            if claim.claim_id == candidate.claim_id:
                continue
            if not _same_scope(claim, candidate):
                continue
            same_topic = normalize_text(claim.topic) == normalize_text(candidate.topic)
            same_target = claim.claim_id in candidate.conflicts or candidate.claim_id in claim.conflicts
            incompatible_statement = normalize_text(claim.statement) != candidate_text
            incompatible_status = claim.status is KnowledgeStatus.VALIDATED and candidate.status is KnowledgeStatus.DEPRECATED
            if (same_topic or same_target) and (incompatible_statement or incompatible_status):
                candidates.append(
                    ConflictCandidate(
                        candidate_id=candidate.claim_id,
                        conflicting_record_ids=(claim.claim_id,),
                        reason="same topic or target with incompatible statement or state",
                    )
                )
        return tuple(candidates)
