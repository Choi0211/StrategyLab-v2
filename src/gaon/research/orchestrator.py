"""Guarded research assistant orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.research.approval import ApprovalDecision, ApprovalRequest, InMemoryApprovalStore, create_approval_request
from gaon.research.planner import plan_research_request
from gaon.research.tasks import ResearchProposal, ResearchRequest, ResearchRun, ResearchRunStatus, ResearchTask


@dataclass(frozen=True)
class QueueItem:
    priority: int
    dedupe_key: str
    task: ResearchTask


class InMemoryResearchQueue:
    def __init__(self, *, max_pending: int = 20) -> None:
        self._items: dict[str, QueueItem] = {}
        self._max_pending = max_pending

    def add(self, item: QueueItem) -> None:
        if item.dedupe_key in self._items:
            raise ValueError("duplicate research queue item")
        if len(self._items) >= self._max_pending:
            raise OverflowError("research queue is full")
        self._items[item.dedupe_key] = item

    def list_pending(self) -> tuple[QueueItem, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: (-item.priority, item.dedupe_key)))


class ResearchOrchestrator:
    def __init__(self, queue: InMemoryResearchQueue | None = None, approvals: InMemoryApprovalStore | None = None, *, approval_signing_secret: str = "test-approval-signing-secret") -> None:
        self._queue = queue or InMemoryResearchQueue()
        self._approvals = approvals or InMemoryApprovalStore()
        self._approval_signing_secret = approval_signing_secret
        self._proposals: dict[str, ResearchProposal] = {}
        self._runs: dict[str, ResearchRun] = {}
        self._audit_events: list[str] = []

    @property
    def audit_events(self) -> tuple[str, ...]:
        return tuple(self._audit_events)

    def propose(self, request: ResearchRequest, *, chat_id: str, approval_token: str, expires_at: str, nonce: str | None = None) -> tuple[ResearchProposal, ApprovalRequest, ResearchRun]:
        proposal = plan_research_request(request)
        approval = create_approval_request(
            f"approval:{proposal.proposal_id}",
            proposal.proposal_id,
            request.actor,
            chat_id,
            approval_token,
            request.created_at,
            expires_at,
            signing_secret=self._approval_signing_secret,
            nonce=nonce,
        )
        run = ResearchRun(f"run:{proposal.proposal_id}", proposal, ResearchRunStatus.PROPOSED).transition(ResearchRunStatus.AWAITING_APPROVAL, event_id=f"audit:{proposal.proposal_id}:awaiting")
        self._proposals[proposal.proposal_id] = proposal
        self._approvals.add(approval)
        self._runs[run.run_id] = run
        self._queue.add(QueueItem(1, proposal.proposal_id, ResearchTask(f"task:{proposal.proposal_id}", proposal.plan.goal)))
        self._audit_events.append(f"proposal_created:{proposal.proposal_id}")
        return proposal, approval, run

    def approve(self, decision: ApprovalDecision, *, now: str) -> ResearchRun:
        approval = self._approvals.approve(decision, now=now, signing_secret=self._approval_signing_secret)
        run = self._runs[f"run:{decision.proposal_id}"]
        approved = run.transition(ResearchRunStatus.APPROVED, event_id=f"audit:{decision.proposal_id}:approved")
        self._runs[approved.run_id] = approved
        self._audit_events.append(f"approved:{decision.proposal_id}:{decision.actor}:{approval.approval_id}")
        return approved

    def start(self, proposal_id: str, *, approval_token: str, actor: str | None = None, chat_id: str | None = None, now: str | None = None) -> ResearchRun:
        run = self._runs[f"run:{proposal_id}"]
        proposal = self._proposals[proposal_id]
        approval = self._approvals.get_by_proposal(proposal_id)
        consumed = self._approvals.consume(
            proposal_id,
            run_id=run.run_id,
            actor=actor or proposal.created_by,
            chat_id=chat_id or approval.requested_chat_id,
            token=approval_token,
            now=now or proposal.created_at,
            signing_secret=self._approval_signing_secret,
        )
        running = run.transition(ResearchRunStatus.RUNNING, approval_token=approval_token, event_id=f"audit:{proposal_id}:running:{consumed.approval_id}")
        self._runs[running.run_id] = running
        self._audit_events.append(f"running:{proposal_id}")
        return running

    def cancel(self, proposal_id: str) -> ResearchRun:
        run = self._runs[f"run:{proposal_id}"]
        cancelled = run.transition(ResearchRunStatus.CANCELLED, event_id=f"audit:{proposal_id}:cancelled")
        self._runs[cancelled.run_id] = cancelled
        self._audit_events.append(f"cancelled:{proposal_id}")
        return cancelled

    def status(self) -> tuple[ResearchRun, ...]:
        return tuple(sorted(self._runs.values(), key=lambda run: run.run_id))
