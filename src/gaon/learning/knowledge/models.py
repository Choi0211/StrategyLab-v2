"""Knowledge state machine for Gaon's Learning Memory."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from gaon.learning.confidence.models import ConfidenceScore
from gaon.learning.evidence.models import EvidenceRecord


class KnowledgeStatus(str, Enum):
    """Knowledge lifecycle states."""

    COLLECTED = "collected"
    REVIEWED = "reviewed"
    NEED_VALIDATION = "need_validation"
    VALIDATED = "validated"
    DEPRECATED = "deprecated"


_ALLOWED_TRANSITIONS: dict[KnowledgeStatus, tuple[KnowledgeStatus, ...]] = {
    KnowledgeStatus.COLLECTED: (KnowledgeStatus.REVIEWED, KnowledgeStatus.DEPRECATED),
    KnowledgeStatus.REVIEWED: (KnowledgeStatus.NEED_VALIDATION, KnowledgeStatus.DEPRECATED),
    KnowledgeStatus.NEED_VALIDATION: (KnowledgeStatus.VALIDATED, KnowledgeStatus.DEPRECATED),
    KnowledgeStatus.VALIDATED: (KnowledgeStatus.DEPRECATED,),
    KnowledgeStatus.DEPRECATED: (),
}


@dataclass(frozen=True)
class KnowledgeItem:
    """Evidence-backed knowledge item."""

    knowledge_id: str
    topic: str
    statement: str
    status: KnowledgeStatus
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore

    def __post_init__(self) -> None:
        if not self.knowledge_id:
            raise ValueError("knowledge_id is required")
        if not self.topic:
            raise ValueError("topic is required")
        if not self.statement:
            raise ValueError("statement is required")
        if not self.evidence:
            raise ValueError("knowledge requires evidence")


def transition_knowledge(
    item: KnowledgeItem,
    target: KnowledgeStatus,
    *,
    user_approved: bool = False,
) -> KnowledgeItem:
    """Move knowledge through the approved lifecycle."""

    if target not in _ALLOWED_TRANSITIONS[item.status]:
        raise ValueError(f"invalid knowledge transition: {item.status.value} -> {target.value}")
    if target is KnowledgeStatus.VALIDATED and not user_approved:
        raise PermissionError("knowledge cannot become validated without user approval")
    return replace(item, status=target)
