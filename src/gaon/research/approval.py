"""Explicit research approval contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import hmac
import secrets
import threading


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    proposal_id: str
    requested_actor: str
    requested_chat_id: str
    token_digest: str
    issued_at: str
    expires_at: str
    nonce: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    consumed_by_run_id: str | None = None

    def approve(self, decision: "ApprovalDecision", *, now: str, signing_secret: str) -> "ApprovalRequest":
        validate_approval(self, decision, now=now, signing_secret=signing_secret)
        return replace(self, status=ApprovalStatus.APPROVED)

    def reject(self) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.PENDING:
            raise PermissionError("approval is not pending")
        return replace(self, status=ApprovalStatus.REJECTED)

    def consume(self, *, run_id: str, actor: str, chat_id: str, token: str, now: str, signing_secret: str) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.APPROVED:
            raise PermissionError("approval is not approved")
        if now > self.expires_at:
            raise PermissionError("approval expired")
        if actor != self.requested_actor or chat_id != self.requested_chat_id:
            raise PermissionError("approval actor mismatch")
        if not verify_approval_token(self, token, signing_secret=signing_secret):
            raise PermissionError("approval token mismatch")
        return replace(self, status=ApprovalStatus.CONSUMED, consumed_by_run_id=run_id)


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    proposal_id: str
    actor: str
    chat_id: str
    token: str
    approved: bool
    decided_at: str


class InMemoryApprovalStore:
    """Thread-safe approval store used until Sprint 19 introduces SQLite repositories."""

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()

    def add(self, approval: ApprovalRequest) -> None:
        with self._lock:
            if approval.approval_id in self._approvals:
                raise ValueError("duplicate approval id")
            self._approvals[approval.approval_id] = approval

    def get(self, approval_id: str) -> ApprovalRequest:
        with self._lock:
            return self._approvals[approval_id]

    def get_by_proposal(self, proposal_id: str) -> ApprovalRequest:
        with self._lock:
            for approval in self._approvals.values():
                if approval.proposal_id == proposal_id:
                    return approval
        raise KeyError(proposal_id)

    def replace(self, approval: ApprovalRequest) -> None:
        with self._lock:
            if approval.approval_id not in self._approvals:
                raise KeyError(approval.approval_id)
            self._approvals[approval.approval_id] = approval

    def approve(self, decision: ApprovalDecision, *, now: str, signing_secret: str) -> ApprovalRequest:
        with self._lock:
            request = self._approvals[decision.approval_id]
            approved = request.approve(decision, now=now, signing_secret=signing_secret)
            self._approvals[approved.approval_id] = approved
            return approved

    def consume(self, proposal_id: str, *, run_id: str, actor: str, chat_id: str, token: str, now: str, signing_secret: str) -> ApprovalRequest:
        with self._lock:
            request = next((approval for approval in self._approvals.values() if approval.proposal_id == proposal_id), None)
            if request is None:
                raise KeyError(proposal_id)
            consumed = request.consume(run_id=run_id, actor=actor, chat_id=chat_id, token=token, now=now, signing_secret=signing_secret)
            self._approvals[consumed.approval_id] = consumed
            return consumed


def create_approval_request(
    approval_id: str,
    proposal_id: str,
    actor: str,
    chat_id: str,
    token: str,
    issued_at: str,
    expires_at: str,
    *,
    signing_secret: str,
    nonce: str | None = None,
) -> ApprovalRequest:
    nonce_value = nonce or secrets.token_urlsafe(16)
    return ApprovalRequest(
        approval_id=approval_id,
        proposal_id=proposal_id,
        requested_actor=actor,
        requested_chat_id=chat_id,
        token_digest=sign_approval_token(
            proposal_id=proposal_id,
            approval_id=approval_id,
            actor=actor,
            chat_id=chat_id,
            issued_at=issued_at,
            expires_at=expires_at,
            nonce=nonce_value,
            token=token,
            signing_secret=signing_secret,
        ),
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce_value,
    )


def validate_approval(request: ApprovalRequest, decision: ApprovalDecision, *, now: str, signing_secret: str) -> None:
    if decision.proposal_id != request.proposal_id or decision.approval_id != request.approval_id:
        raise PermissionError("approval target mismatch")
    if decision.actor != request.requested_actor or decision.chat_id != request.requested_chat_id:
        raise PermissionError("approval actor mismatch")
    if request.status is not ApprovalStatus.PENDING:
        raise PermissionError("approval is not pending")
    if not verify_approval_token(request, decision.token, signing_secret=signing_secret):
        raise PermissionError("approval token mismatch")
    if now > request.expires_at:
        raise PermissionError("approval expired")
    if not decision.approved:
        raise PermissionError("approval rejected")


def verify_approval_token(request: ApprovalRequest, token: str, *, signing_secret: str) -> bool:
    expected = sign_approval_token(
        proposal_id=request.proposal_id,
        approval_id=request.approval_id,
        actor=request.requested_actor,
        chat_id=request.requested_chat_id,
        issued_at=request.issued_at,
        expires_at=request.expires_at,
        nonce=request.nonce,
        token=token,
        signing_secret=signing_secret,
    )
    return hmac.compare_digest(expected, request.token_digest)


def sign_approval_token(
    *,
    proposal_id: str,
    approval_id: str,
    actor: str,
    chat_id: str,
    issued_at: str,
    expires_at: str,
    nonce: str,
    token: str,
    signing_secret: str,
) -> str:
    if not signing_secret:
        raise ValueError("approval signing secret is required")
    payload = "\n".join((proposal_id, approval_id, actor, chat_id, issued_at, expires_at, nonce, token))
    return hmac.new(signing_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
