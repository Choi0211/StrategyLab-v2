"""Research task and run contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class ResearchRunStatus(str, Enum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_RUN_TRANSITIONS = {
    ResearchRunStatus.PROPOSED: (ResearchRunStatus.AWAITING_APPROVAL,),
    ResearchRunStatus.AWAITING_APPROVAL: (ResearchRunStatus.APPROVED, ResearchRunStatus.CANCELLED),
    ResearchRunStatus.APPROVED: (ResearchRunStatus.RUNNING, ResearchRunStatus.CANCELLED),
    ResearchRunStatus.RUNNING: (ResearchRunStatus.PAUSED, ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED),
    ResearchRunStatus.PAUSED: (ResearchRunStatus.RUNNING, ResearchRunStatus.CANCELLED),
    ResearchRunStatus.COMPLETED: (),
    ResearchRunStatus.FAILED: (),
    ResearchRunStatus.CANCELLED: (),
}


@dataclass(frozen=True)
class ResearchRequest:
    request_id: str
    actor: str
    text: str
    created_at: str


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    description: str
    status: ResearchTaskStatus = ResearchTaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 2
    failure_reason: str | None = None

    def retry(self, reason: str) -> "ResearchTask":
        if self.retry_count >= self.max_retries:
            return replace(self, status=ResearchTaskStatus.FAILED, failure_reason=reason)
        return replace(self, retry_count=self.retry_count + 1, failure_reason=reason)


@dataclass(frozen=True)
class ResearchExecutionPlan:
    plan_id: str
    goal: str
    scope: str
    hypothesis: str
    required_data: tuple[str, ...]
    validation_method: str
    risks: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    approval_required: bool = True


@dataclass(frozen=True)
class ResearchProposal:
    proposal_id: str
    request_id: str
    plan: ResearchExecutionPlan
    created_by: str
    created_at: str


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    proposal: ResearchProposal
    status: ResearchRunStatus
    audit_events: tuple[str, ...] = ()

    def transition(self, status: ResearchRunStatus, *, approval_token: str | None = None, event_id: str = "event") -> "ResearchRun":
        if status is ResearchRunStatus.RUNNING and approval_token is None:
            raise PermissionError("running requires explicit approval token")
        if status not in _RUN_TRANSITIONS[self.status]:
            raise ValueError(f"invalid transition: {self.status.value} -> {status.value}")
        return replace(self, status=status, audit_events=(*self.audit_events, event_id))
