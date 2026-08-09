"""Sprint 185 - Human-gated Autonomous Research Promotion.

Validates explicit human approval for an autonomous research promotion
candidate while keeping strategy application manual and audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
from typing import Mapping

from .promotion_gate import (
    PromotionCandidateRecord,
    PromotionGateStatus,
    promotion_candidate_gate_release_check,
)


HUMAN_GATED_PROMOTION_SCHEMA_VERSION = 1


class HumanGatedPromotionStatus(str, Enum):
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    APPROVED_FOR_MANUAL_APPLICATION = "approved_for_manual_application"
    BLOCKED = "blocked"


class HumanGatedPromotionBlocker(str, Enum):
    CANDIDATE_NOT_APPROVAL_READY = "candidate_not_approval_ready"
    MISSING_APPROVAL = "missing_approval"
    INVALID_APPROVAL_TOKEN = "invalid_approval_token"
    APPROVAL_CANDIDATE_MISMATCH = "approval_candidate_mismatch"


@dataclass(frozen=True)
class HumanApprovalReceipt:
    approval_id: str
    candidate_id: str
    approved_by: str
    approved_at: str
    token_digest: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": HUMAN_GATED_PROMOTION_SCHEMA_VERSION,
            "approval_id": self.approval_id,
            "candidate_id": self.candidate_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "token_digest": self.token_digest,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HumanGatedPromotionResult:
    candidate_id: str
    status: HumanGatedPromotionStatus
    blockers: tuple[HumanGatedPromotionBlocker, ...]
    approval: HumanApprovalReceipt | None
    manual_application_required: bool = True
    automatic_champion_promotion: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": HUMAN_GATED_PROMOTION_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "blockers": [item.value for item in self.blockers],
            "approval": self.approval.to_json() if self.approval else None,
            "manual_application_required": self.manual_application_required,
            "automatic_champion_promotion": self.automatic_champion_promotion,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class HumanGatedPromotionService:
    def evaluate(
        self,
        candidate: PromotionCandidateRecord,
        *,
        approval_token: str | None,
        signing_secret: str,
        approved_by: str,
        approved_at: str,
        reason: str,
    ) -> HumanGatedPromotionResult:
        blockers: list[HumanGatedPromotionBlocker] = []
        if candidate.status is not PromotionGateStatus.REQUIRES_HUMAN_APPROVAL:
            blockers.append(HumanGatedPromotionBlocker.CANDIDATE_NOT_APPROVAL_READY)
        if not approval_token:
            blockers.append(HumanGatedPromotionBlocker.MISSING_APPROVAL)
            return HumanGatedPromotionResult(
                candidate_id=candidate.candidate_id,
                status=HumanGatedPromotionStatus.AWAITING_HUMAN_APPROVAL,
                blockers=tuple(dict.fromkeys(blockers)),
                approval=None,
            )
        if not _valid_approval_token(candidate.candidate_id, approval_token, signing_secret):
            blockers.append(HumanGatedPromotionBlocker.INVALID_APPROVAL_TOKEN)
        if blockers:
            return HumanGatedPromotionResult(
                candidate_id=candidate.candidate_id,
                status=HumanGatedPromotionStatus.BLOCKED,
                blockers=tuple(dict.fromkeys(blockers)),
                approval=None,
            )
        receipt = HumanApprovalReceipt(
            approval_id=_approval_id(candidate.candidate_id, approved_by, approved_at),
            candidate_id=candidate.candidate_id,
            approved_by=approved_by,
            approved_at=approved_at,
            token_digest=hashlib.sha256(approval_token.encode("utf-8")).hexdigest(),
            reason=reason,
        )
        return HumanGatedPromotionResult(
            candidate_id=candidate.candidate_id,
            status=HumanGatedPromotionStatus.APPROVED_FOR_MANUAL_APPLICATION,
            blockers=(),
            approval=receipt,
            production_approved=True,
        )


def approval_token_for_candidate(candidate_id: str, signing_secret: str) -> str:
    return hmac.new(
        signing_secret.encode("utf-8"),
        candidate_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _valid_approval_token(candidate_id: str, token: str, signing_secret: str) -> bool:
    expected = approval_token_for_candidate(candidate_id, signing_secret)
    return hmac.compare_digest(expected, token)


def _approval_id(candidate_id: str, approved_by: str, approved_at: str) -> str:
    encoded = json.dumps(
        {
            "candidate_id": candidate_id,
            "approved_by": approved_by,
            "approved_at": approved_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"human-approval:{hashlib.sha256(encoded).hexdigest()}"


def human_gated_promotion_release_check() -> Mapping[str, object]:
    promotion_payload = promotion_candidate_gate_release_check()
    from .promotion_gate import PromotionCandidateGate
    from .robustness_ranking import RobustnessRankingResult, RobustnessRankingStatus, RobustnessRankedStrategy

    ranking = RobustnessRankingResult(
        status=RobustnessRankingStatus.RANKED,
        blockers=(),
        ranked=(
            RobustnessRankedStrategy(
                rank=1,
                experiment_id="strategy-experiment:human-gate",
                evidence_id="validation-evidence:human-gate",
                score=4.2,
                trade_count=60,
                total_return=0.18,
                mdd=0.09,
                profit_factor=1.6,
                win_rate=0.56,
                source="real:yahoo-chart",
                fixture_backed=False,
            ),
        ),
        warnings=(),
    )
    candidate = PromotionCandidateGate().evaluate(
        ranking,
        rollback_target="strategy-config:default:active",
    )
    secret = "release-check-secret"
    token = approval_token_for_candidate(candidate.candidate_id, secret)
    service = HumanGatedPromotionService()
    awaiting = service.evaluate(
        candidate,
        approval_token=None,
        signing_secret=secret,
        approved_by="actor:redacted",
        approved_at="2026-08-08T00:00:00+00:00",
        reason="release check",
    )
    approved = service.evaluate(
        candidate,
        approval_token=token,
        signing_secret=secret,
        approved_by="actor:redacted",
        approved_at="2026-08-08T00:00:00+00:00",
        reason="release check",
    )
    invalid = service.evaluate(
        candidate,
        approval_token="invalid",
        signing_secret=secret,
        approved_by="actor:redacted",
        approved_at="2026-08-08T00:00:00+00:00",
        reason="release check",
    )
    checks = {
        "promotion_ready": promotion_payload["status"] == "requires_human_approval",
        "awaiting_without_token": awaiting.status is HumanGatedPromotionStatus.AWAITING_HUMAN_APPROVAL,
        "approved_manual_only": approved.status is HumanGatedPromotionStatus.APPROVED_FOR_MANUAL_APPLICATION,
        "invalid_blocked": HumanGatedPromotionBlocker.INVALID_APPROVAL_TOKEN in invalid.blockers,
        "no_auto_promotion": not approved.automatic_champion_promotion,
        "no_mutation": not approved.strategy_mutated and not approved.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"human gated promotion release check failed: {failed}")
    return {
        "schema_version": HUMAN_GATED_PROMOTION_SCHEMA_VERSION,
        "status": approved.status.value,
        "manual_application_required": approved.manual_application_required,
        "approval_id": approved.approval.approval_id if approved.approval else "",
        "checks": checks,
        "safety": "pass",
    }


def autonomous_learning_production_gate_release_check() -> Mapping[str, object]:
    payload = human_gated_promotion_release_check()
    checks = {
        "human_gate": payload["status"] == "approved_for_manual_application",
        "manual_application": payload["manual_application_required"] is True,
        "safety": payload["safety"] == "pass",
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"autonomous learning production gate release check failed: {failed}")
    return {
        "schema_version": HUMAN_GATED_PROMOTION_SCHEMA_VERSION,
        "status": "production_gate_ready",
        "checks": checks,
        "safety": "pass",
    }
