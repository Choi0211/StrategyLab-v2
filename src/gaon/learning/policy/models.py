"""Policy update contracts for Gaon's autonomous learning boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from gaon.learning.evidence.models import EvidenceRecord


class AutonomousAction(str, Enum):
    """Actions Gaon must not perform autonomously."""

    MODIFY_SOURCE_CODE = "modify_source_code"
    CHANGE_PROMPT = "change_prompt"
    OPERATE_CHAMPION = "operate_champion"
    CHANGE_SECRET = "change_secret"
    CHANGE_TRADING_RULE = "change_trading_rule"
    DELETE_USER_PREFERENCE = "delete_user_preference"


@dataclass(frozen=True)
class PolicyUpdateCandidate:
    """Policy change proposal that requires approval and rollback metadata."""

    policy_id: str
    proposed_change: str
    evidence: tuple[EvidenceRecord, ...]
    rollback_ref: str
    approved_by: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id is required")
        if not self.proposed_change:
            raise ValueError("proposed_change is required")
        if not self.evidence:
            raise ValueError("policy update requires evidence")
        if not self.rollback_ref:
            raise ValueError("rollback_ref is required")

    @property
    def is_approved(self) -> bool:
        return self.approved_by is not None

    def approve(self, user: str) -> "PolicyUpdateCandidate":
        if not user:
            raise ValueError("approval user is required")
        return replace(self, approved_by=user)
