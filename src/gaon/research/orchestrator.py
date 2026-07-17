"""Guarded research assistant orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.research.approval import ApprovalDecision, ApprovalRequest, validate_approval
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
    def __init__(self, queue: InMemoryResearchQueue | None = None) -> None:
        self._queue = queue or InMemoryResearchQueue()
        self._proposals: dict[str, ResearchProposal] = {}
        self._runs: dict[str, ResearchRun] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._audit_events: list[str] = []

    @property
    def audit_events(self) -> tuple[str, ...]:
        return tuple(self._audit_events)

    def propose(self, request: ResearchRequest, *, chat_id: str, approval_token: str, expires_at: str) -> tuple[ResearchProposal, ApprovalRequest, ResearchRun]:
        proposal = plan_research_request(request)
        approval = ApprovalRequest(f"approval:{proposal.proposal_id}", proposal.proposal_id, request.actor, chat_id, approval_token, expires_at)
        run = ResearchRun(f"run:{proposal.proposal_id}", proposal, ResearchRunStatus.PROPOSED).transition(ResearchRunStatus.AWAITING_APPROVAL, event_id=f"audit:{proposal.proposal_id}:awaiting")
        self._proposals[proposal.proposal_id] = proposal
        self._approvals[proposal.proposal_id] = approval
        self._runs[run.run_id] = run
        self._queue.add(QueueItem(1, proposal.proposal_id, ResearchTask(f"task:{proposal.proposal_id}", proposal.plan.goal)))
        self._audit_events.append(f"proposal_created:{proposal.proposal_id}")
        return proposal, approval, run

    def approve(self, decision: ApprovalDecision, *, now: str) -> ResearchRun:
        request = self._approvals[decision.proposal_id]
        validate_approval(request, decision, now=now)
        run = self._runs[f"run:{decision.proposal_id}"]
        approved = run.transition(ResearchRunStatus.APPROVED, event_id=f"audit:{decision.proposal_id}:approved")
        self._runs[approved.run_id] = approved
        self._audit_events.append(f"approved:{decision.proposal_id}:{decision.actor}")
        return approved

    def start(self, proposal_id: str, *, approval_token: str) -> ResearchRun:
        run = self._runs[f"run:{proposal_id}"]
        running = run.transition(ResearchRunStatus.RUNNING, approval_token=approval_token, event_id=f"audit:{proposal_id}:running")
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
