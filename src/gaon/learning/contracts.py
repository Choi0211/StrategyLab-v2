"""Sprint 12-A Learning Memory domain contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from gaon.learning.confidence.models import ConfidenceScore
from gaon.learning.evidence.models import EvidenceRecord, EvidenceType
from gaon.learning.knowledge.models import KnowledgeStatus

LEARNING_CONTRACT_SCHEMA_VERSION = 1


class LearningRecordType(str, Enum):
    """Learning Memory record types."""

    KNOWLEDGE_CLAIM = "knowledge_claim"
    RESEARCH_OUTCOME = "research_outcome"
    FAILURE_PATTERN = "failure_pattern"
    SUCCESS_PATTERN = "success_pattern"
    USER_PREFERENCE = "user_preference"
    CONVERSATION_SUMMARY = "conversation_summary"


class RevalidationStatus(str, Enum):
    """Revalidation schedule state."""

    PENDING = "pending"
    DUE = "due"
    COMPLETED = "completed"


class AuditAction(str, Enum):
    """Auditable Learning Memory actions."""

    CREATE = "create"
    UPDATE = "update"
    TRANSITION = "transition"
    APPROVE = "approve"
    DEPRECATE = "deprecate"
    ROLLBACK = "rollback"


def _versioned_payload(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": LEARNING_CONTRACT_SCHEMA_VERSION, "kind": kind, "data": data}


def _load_versioned_json(payload: str, expected_kind: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    if decoded.get("schema_version") != LEARNING_CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported Learning Memory schema version")
    if decoded.get("kind") != expected_kind:
        raise ValueError(f"expected {expected_kind} payload")
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise ValueError("Learning Memory payload data must be an object")
    return data


def _require_text(value: str, field: str) -> None:
    if not value:
        raise ValueError(f"{field} is required")


def _require_scope(scope: str, project: str, strategy: str, market: str) -> None:
    _require_text(scope, "scope")
    _require_text(project, "project")
    _require_text(strategy, "strategy")
    _require_text(market, "market")


def _require_evidence(evidence: tuple[EvidenceRecord, ...], owner: str) -> None:
    if not evidence:
        raise ValueError(f"{owner} requires evidence")


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


def _evidence_tuple_to_list(evidence: tuple[EvidenceRecord, ...]) -> list[dict[str, str]]:
    return [_evidence_to_dict(record) for record in evidence]


def _evidence_tuple_from_list(items: list[dict[str, str]]) -> tuple[EvidenceRecord, ...]:
    return tuple(_evidence_from_dict(item) for item in items)


def _confidence_to_dict(confidence: ConfidenceScore) -> dict[str, Any]:
    return confidence.to_dict()


def _confidence_from_dict(data: dict[str, Any]) -> ConfidenceScore:
    return ConfidenceScore.from_dict(data)


@dataclass(frozen=True)
class RevalidationSchedule:
    """Planned revalidation metadata."""

    schedule_id: str
    target_ref: str
    reason: str
    due_at: str
    frequency: str
    status: RevalidationStatus
    scope: str
    project: str
    strategy: str
    market: str

    def __post_init__(self) -> None:
        _require_text(self.schedule_id, "schedule_id")
        _require_text(self.target_ref, "target_ref")
        _require_text(self.reason, "reason")
        _require_text(self.due_at, "due_at")
        _require_text(self.frequency, "frequency")
        _require_scope(self.scope, self.project, self.strategy, self.market)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "target_ref": self.target_ref,
            "reason": self.reason,
            "due_at": self.due_at,
            "frequency": self.frequency,
            "status": self.status.value,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RevalidationSchedule":
        return cls(
            schedule_id=data["schedule_id"],
            target_ref=data["target_ref"],
            reason=data["reason"],
            due_at=data["due_at"],
            frequency=data["frequency"],
            status=RevalidationStatus(data["status"]),
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("revalidation_schedule", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "RevalidationSchedule":
        return cls.from_dict(_load_versioned_json(payload, "revalidation_schedule"))


@dataclass(frozen=True)
class KnowledgeApproval:
    """Approval required for Validated knowledge."""

    approval_id: str
    claim_id: str
    approved_by: str
    approved_at: str
    evidence: tuple[EvidenceRecord, ...]
    scope: str
    project: str
    strategy: str
    market: str

    def __post_init__(self) -> None:
        _require_text(self.approval_id, "approval_id")
        _require_text(self.claim_id, "claim_id")
        _require_text(self.approved_by, "approved_by")
        _require_text(self.approved_at, "approved_at")
        _require_evidence(self.evidence, "knowledge approval")
        _require_scope(self.scope, self.project, self.strategy, self.market)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "claim_id": self.claim_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeApproval":
        return cls(
            approval_id=data["approval_id"],
            claim_id=data["claim_id"],
            approved_by=data["approved_by"],
            approved_at=data["approved_at"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("knowledge_approval", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "KnowledgeApproval":
        return cls.from_dict(_load_versioned_json(payload, "knowledge_approval"))


@dataclass(frozen=True)
class PolicyApproval:
    """Approval required before applying a policy revision."""

    approval_id: str
    revision_id: str
    approved_by: str
    approved_at: str
    evidence: tuple[EvidenceRecord, ...]
    rollback_ref: str
    scope: str
    project: str
    strategy: str
    market: str

    def __post_init__(self) -> None:
        _require_text(self.approval_id, "approval_id")
        _require_text(self.revision_id, "revision_id")
        _require_text(self.approved_by, "approved_by")
        _require_text(self.approved_at, "approved_at")
        _require_text(self.rollback_ref, "rollback_ref")
        _require_evidence(self.evidence, "policy approval")
        _require_scope(self.scope, self.project, self.strategy, self.market)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "revision_id": self.revision_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "rollback_ref": self.rollback_ref,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyApproval":
        return cls(
            approval_id=data["approval_id"],
            revision_id=data["revision_id"],
            approved_by=data["approved_by"],
            approved_at=data["approved_at"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            rollback_ref=data["rollback_ref"],
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("policy_approval", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "PolicyApproval":
        return cls.from_dict(_load_versioned_json(payload, "policy_approval"))


@dataclass(frozen=True)
class LearningRecord:
    """Canonical evidence-backed memory envelope."""

    record_id: str
    record_type: LearningRecordType
    content: str
    scope: str
    project: str
    strategy: str
    market: str
    created_at: str
    updated_at: str
    version: int
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore
    revalidation: RevalidationSchedule
    audit_ref: str

    def __post_init__(self) -> None:
        _require_text(self.record_id, "record_id")
        _require_text(self.content, "content")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_text(self.created_at, "created_at")
        _require_text(self.updated_at, "updated_at")
        if self.version < 1:
            raise ValueError("version must be positive")
        _require_evidence(self.evidence, "learning record")
        _require_text(self.audit_ref, "audit_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type.value,
            "content": self.content,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "confidence": _confidence_to_dict(self.confidence),
            "revalidation": self.revalidation.to_dict(),
            "audit_ref": self.audit_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearningRecord":
        return cls(
            record_id=data["record_id"],
            record_type=LearningRecordType(data["record_type"]),
            content=data["content"],
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            version=data["version"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            confidence=_confidence_from_dict(data["confidence"]),
            revalidation=RevalidationSchedule.from_dict(data["revalidation"]),
            audit_ref=data["audit_ref"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("learning_record", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "LearningRecord":
        return cls.from_dict(_load_versioned_json(payload, "learning_record"))


@dataclass(frozen=True)
class KnowledgeClaim:
    """Evidence-backed claim with approval-gated validation."""

    claim_id: str
    statement: str
    topic: str
    status: KnowledgeStatus
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore
    conflicts: tuple[str, ...]
    approval: KnowledgeApproval | None = None

    def __post_init__(self) -> None:
        _require_text(self.claim_id, "claim_id")
        _require_text(self.statement, "statement")
        _require_text(self.topic, "topic")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "knowledge claim")
        if any(not conflict for conflict in self.conflicts):
            raise ValueError("conflicts must not contain empty values")
        if self.status is KnowledgeStatus.VALIDATED and self.approval is None:
            raise PermissionError("validated knowledge requires KnowledgeApproval")

    def validate(self, approval: KnowledgeApproval | None = None) -> "KnowledgeClaim":
        if approval is None:
            raise PermissionError("KnowledgeApproval is required")
        if approval.claim_id != self.claim_id:
            raise ValueError("KnowledgeApproval claim_id mismatch")
        if self.conflicts:
            raise ValueError("conflicting claims cannot be validated")
        return replace(self, status=KnowledgeStatus.VALIDATED, approval=approval)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "topic": self.topic,
            "status": self.status.value,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "confidence": _confidence_to_dict(self.confidence),
            "conflicts": list(self.conflicts),
            "approval": self.approval.to_dict() if self.approval else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeClaim":
        approval = data.get("approval")
        return cls(
            claim_id=data["claim_id"],
            statement=data["statement"],
            topic=data["topic"],
            status=KnowledgeStatus(data["status"]),
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            confidence=_confidence_from_dict(data["confidence"]),
            conflicts=tuple(data["conflicts"]),
            approval=KnowledgeApproval.from_dict(approval) if approval else None,
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("knowledge_claim", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "KnowledgeClaim":
        return cls.from_dict(_load_versioned_json(payload, "knowledge_claim"))


@dataclass(frozen=True)
class ResearchOutcome:
    outcome_id: str
    research_goal_id: str
    experiment_id: str
    result_summary: str
    metrics: dict[str, float]
    conclusion: str
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore

    def __post_init__(self) -> None:
        _require_text(self.outcome_id, "outcome_id")
        _require_text(self.research_goal_id, "research_goal_id")
        _require_text(self.experiment_id, "experiment_id")
        _require_text(self.result_summary, "result_summary")
        _require_text(self.conclusion, "conclusion")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "research outcome")

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "evidence": _evidence_tuple_to_list(self.evidence), "confidence": _confidence_to_dict(self.confidence)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchOutcome":
        return cls(**{**data, "evidence": _evidence_tuple_from_list(data["evidence"]), "confidence": _confidence_from_dict(data["confidence"])})

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("research_outcome", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "ResearchOutcome":
        return cls.from_dict(_load_versioned_json(payload, "research_outcome"))


@dataclass(frozen=True)
class FailurePattern:
    failure_id: str
    cause: str
    symptom: str
    context: str
    avoidance_rule: str
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore

    def __post_init__(self) -> None:
        _require_text(self.failure_id, "failure_id")
        _require_text(self.cause, "cause")
        _require_text(self.symptom, "symptom")
        _require_text(self.context, "context")
        _require_text(self.avoidance_rule, "avoidance_rule")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "failure pattern")

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "evidence": _evidence_tuple_to_list(self.evidence), "confidence": _confidence_to_dict(self.confidence)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailurePattern":
        return cls(**{**data, "evidence": _evidence_tuple_from_list(data["evidence"]), "confidence": _confidence_from_dict(data["confidence"])})

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("failure_pattern", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "FailurePattern":
        return cls.from_dict(_load_versioned_json(payload, "failure_pattern"))


@dataclass(frozen=True)
class SuccessPattern:
    success_id: str
    pattern: str
    context: str
    repeatability_notes: str
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore

    def __post_init__(self) -> None:
        _require_text(self.success_id, "success_id")
        _require_text(self.pattern, "pattern")
        _require_text(self.context, "context")
        _require_text(self.repeatability_notes, "repeatability_notes")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "success pattern")

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "evidence": _evidence_tuple_to_list(self.evidence), "confidence": _confidence_to_dict(self.confidence)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SuccessPattern":
        return cls(**{**data, "evidence": _evidence_tuple_from_list(data["evidence"]), "confidence": _confidence_from_dict(data["confidence"])})

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("success_pattern", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "SuccessPattern":
        return cls.from_dict(_load_versioned_json(payload, "success_pattern"))


@dataclass(frozen=True)
class LearningProposal:
    proposal_id: str
    proposal_type: str
    target_ref: str
    change_summary: str
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore
    approval_required: bool

    def __post_init__(self) -> None:
        _require_text(self.proposal_id, "proposal_id")
        _require_text(self.proposal_type, "proposal_type")
        _require_text(self.target_ref, "target_ref")
        _require_text(self.change_summary, "change_summary")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "learning proposal")

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "evidence": _evidence_tuple_to_list(self.evidence), "confidence": _confidence_to_dict(self.confidence)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearningProposal":
        return cls(**{**data, "evidence": _evidence_tuple_from_list(data["evidence"]), "confidence": _confidence_from_dict(data["confidence"])})

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("learning_proposal", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "LearningProposal":
        return cls.from_dict(_load_versioned_json(payload, "learning_proposal"))


@dataclass(frozen=True)
class UserPreference:
    preference_id: str
    preference: str
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore
    version: int
    approval: PolicyApproval | None = None

    def __post_init__(self) -> None:
        _require_text(self.preference_id, "preference_id")
        _require_text(self.preference, "preference")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "user preference")
        if self.version < 1:
            raise ValueError("version must be positive")

    def overwrite_automatically(self, new_preference: str) -> "UserPreference":
        raise PermissionError("user preferences cannot be overwritten automatically")

    def delete_automatically(self) -> None:
        raise PermissionError("user preferences cannot be deleted automatically")

    def propose_change(self, proposal_id: str, new_preference: str, evidence: tuple[EvidenceRecord, ...]) -> LearningProposal:
        _require_text(new_preference, "new_preference")
        return LearningProposal(
            proposal_id=proposal_id,
            proposal_type="user_preference_change",
            target_ref=self.preference_id,
            change_summary=new_preference,
            scope=self.scope,
            project=self.project,
            strategy=self.strategy,
            market=self.market,
            evidence=evidence,
            confidence=self.confidence,
            approval_required=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preference_id": self.preference_id,
            "preference": self.preference,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "confidence": _confidence_to_dict(self.confidence),
            "version": self.version,
            "approval": self.approval.to_dict() if self.approval else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserPreference":
        approval = data.get("approval")
        return cls(
            preference_id=data["preference_id"],
            preference=data["preference"],
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            confidence=_confidence_from_dict(data["confidence"]),
            version=data["version"],
            approval=PolicyApproval.from_dict(approval) if approval else None,
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("user_preference", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "UserPreference":
        return cls.from_dict(_load_versioned_json(payload, "user_preference"))


@dataclass(frozen=True)
class ConversationSummary:
    summary_id: str
    conversation_ref: str
    summary: str
    decisions: tuple[str, ...]
    todos: tuple[str, ...]
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    confidence: ConfidenceScore

    def __post_init__(self) -> None:
        _require_text(self.summary_id, "summary_id")
        _require_text(self.conversation_ref, "conversation_ref")
        _require_text(self.summary, "summary")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "conversation summary")
        if any(not item for item in self.decisions):
            raise ValueError("decisions must not contain empty values")
        if any(not item for item in self.todos):
            raise ValueError("todos must not contain empty values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "conversation_ref": self.conversation_ref,
            "summary": self.summary,
            "decisions": list(self.decisions),
            "todos": list(self.todos),
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "confidence": _confidence_to_dict(self.confidence),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationSummary":
        return cls(
            summary_id=data["summary_id"],
            conversation_ref=data["conversation_ref"],
            summary=data["summary"],
            decisions=tuple(data["decisions"]),
            todos=tuple(data["todos"]),
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            confidence=_confidence_from_dict(data["confidence"]),
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("conversation_summary", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "ConversationSummary":
        return cls.from_dict(_load_versioned_json(payload, "conversation_summary"))


@dataclass(frozen=True)
class PolicyRevision:
    revision_id: str
    policy_ref: str
    proposed_change: str
    previous_version: int
    next_version: int
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    rollback_ref: str
    approval: PolicyApproval | None = None
    applied: bool = False

    def __post_init__(self) -> None:
        _require_text(self.revision_id, "revision_id")
        _require_text(self.policy_ref, "policy_ref")
        _require_text(self.proposed_change, "proposed_change")
        if self.previous_version < 1 or self.next_version <= self.previous_version:
            raise ValueError("policy revision versions are invalid")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "policy revision")
        _require_text(self.rollback_ref, "rollback_ref")
        if self.applied and self.approval is None:
            raise PermissionError("applied policy revision requires PolicyApproval")

    def apply(self, approval: PolicyApproval | None = None) -> "PolicyRevision":
        if approval is None:
            raise PermissionError("PolicyApproval is required")
        if approval.revision_id != self.revision_id:
            raise ValueError("PolicyApproval revision_id mismatch")
        if approval.rollback_ref != self.rollback_ref:
            raise ValueError("PolicyApproval rollback_ref mismatch")
        return replace(self, approval=approval, applied=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "policy_ref": self.policy_ref,
            "proposed_change": self.proposed_change,
            "previous_version": self.previous_version,
            "next_version": self.next_version,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "rollback_ref": self.rollback_ref,
            "approval": self.approval.to_dict() if self.approval else None,
            "applied": self.applied,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyRevision":
        approval = data.get("approval")
        return cls(
            revision_id=data["revision_id"],
            policy_ref=data["policy_ref"],
            proposed_change=data["proposed_change"],
            previous_version=data["previous_version"],
            next_version=data["next_version"],
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            rollback_ref=data["rollback_ref"],
            approval=PolicyApproval.from_dict(approval) if approval else None,
            applied=data["applied"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("policy_revision", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "PolicyRevision":
        return cls.from_dict(_load_versioned_json(payload, "policy_revision"))


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    actor: str
    action: AuditAction
    target_ref: str
    before_version: int | None
    after_version: int
    scope: str
    project: str
    strategy: str
    market: str
    evidence: tuple[EvidenceRecord, ...]
    timestamp: str
    rollback_ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.actor, "actor")
        _require_text(self.target_ref, "target_ref")
        if self.before_version is not None and self.before_version < 1:
            raise ValueError("before_version must be positive when provided")
        if self.after_version < 1:
            raise ValueError("after_version must be positive")
        _require_scope(self.scope, self.project, self.strategy, self.market)
        _require_evidence(self.evidence, "audit event")
        _require_text(self.timestamp, "timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "actor": self.actor,
            "action": self.action.value,
            "target_ref": self.target_ref,
            "before_version": self.before_version,
            "after_version": self.after_version,
            "scope": self.scope,
            "project": self.project,
            "strategy": self.strategy,
            "market": self.market,
            "evidence": _evidence_tuple_to_list(self.evidence),
            "timestamp": self.timestamp,
            "rollback_ref": self.rollback_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEvent":
        return cls(
            event_id=data["event_id"],
            actor=data["actor"],
            action=AuditAction(data["action"]),
            target_ref=data["target_ref"],
            before_version=data["before_version"],
            after_version=data["after_version"],
            scope=data["scope"],
            project=data["project"],
            strategy=data["strategy"],
            market=data["market"],
            evidence=_evidence_tuple_from_list(data["evidence"]),
            timestamp=data["timestamp"],
            rollback_ref=data["rollback_ref"],
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("audit_event", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "AuditEvent":
        return cls.from_dict(_load_versioned_json(payload, "audit_event"))
