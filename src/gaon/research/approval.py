"""Explicit research approval contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    proposal_id: str
    requested_actor: str
    requested_chat_id: str
    token: str
    expires_at: str


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    proposal_id: str
    actor: str
    chat_id: str
    token: str
    approved: bool
    decided_at: str


def validate_approval(request: ApprovalRequest, decision: ApprovalDecision, *, now: str) -> None:
    if decision.proposal_id != request.proposal_id or decision.approval_id != request.approval_id:
        raise PermissionError("approval target mismatch")
    if decision.actor != request.requested_actor or decision.chat_id != request.requested_chat_id:
        raise PermissionError("approval actor mismatch")
    if decision.token != request.token:
        raise PermissionError("approval token mismatch")
    if now > request.expires_at:
        raise PermissionError("approval expired")
    if not decision.approved:
        raise PermissionError("approval rejected")
