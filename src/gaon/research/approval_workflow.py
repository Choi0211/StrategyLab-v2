"""Auditable research approval workflow for knowledge proposals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3

from gaon.research.knowledge import KnowledgeProposal, KnowledgeProposalStatus
from gaon.runtime.event_store import DurableEvent
from gaon.runtime.metrics import MetricsCollector


class ResearchDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"


@dataclass(frozen=True)
class ResearchApprovalRequest:
    request_id: str
    proposal_id: str
    proposal_hash: str
    proposal_version: int
    actor_ref: str
    created_at: str


@dataclass(frozen=True)
class ResearchApprovalDecision:
    decision_id: str
    proposal_id: str
    proposal_hash: str
    proposal_version: int
    actor_ref: str
    decision: ResearchDecision
    reason: str
    decided_at: str


def build_approval_request(proposal: KnowledgeProposal, *, actor_ref: str, created_at: str) -> ResearchApprovalRequest:
    return ResearchApprovalRequest(f"approval-request:{proposal.proposal_id}:{proposal.version}", proposal.proposal_id, proposal.proposal_hash, proposal.version, actor_ref, created_at)


def decide(request: ResearchApprovalRequest, proposal: KnowledgeProposal, *, decision: ResearchDecision, reason: str, decided_at: str) -> ResearchApprovalDecision:
    if proposal.proposal_hash != request.proposal_hash or proposal.version != request.proposal_version:
        raise PermissionError("stale proposal approval request")
    if proposal.status is KnowledgeProposalStatus.REJECTED and decision is ResearchDecision.APPROVE:
        raise PermissionError("rejected proposal cannot be approved")
    return ResearchApprovalDecision(
        f"decision:{request.proposal_id}:{request.proposal_hash[:12]}:{request.actor_ref}:{decision.value}",
        request.proposal_id,
        request.proposal_hash,
        request.proposal_version,
        request.actor_ref,
        decision,
        reason,
        decided_at,
    )


class SQLiteResearchApprovalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_decision(self, decision: ResearchApprovalDecision) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO research_approval_decisions(
                        decision_id, proposal_id, proposal_hash, proposal_version, actor_ref,
                        decision, reason, decided_at, consumed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.proposal_hash,
                        decision.proposal_version,
                        decision.actor_ref,
                        decision.decision.value,
                        decision.reason,
                        decision.decided_at,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_decisions(self) -> tuple[ResearchApprovalDecision, ...]:
        rows = self._connection.execute("SELECT decision_id, proposal_id, proposal_hash, proposal_version, actor_ref, decision, reason, decided_at FROM research_approval_decisions ORDER BY decided_at, decision_id").fetchall()
        return tuple(
            ResearchApprovalDecision(str(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4]), ResearchDecision(str(row[5])), str(row[6]), str(row[7]))
            for row in rows
        )

    def consume_for_promotion(self, decision: ResearchApprovalDecision) -> bool:
        if decision.decision is not ResearchDecision.APPROVE:
            raise PermissionError("only approved decisions can promote trusted knowledge")
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE research_approval_decisions SET consumed = 1 WHERE decision_id = ? AND consumed = 0",
                (decision.decision_id,),
            )
        return cursor.rowcount == 1


def approval_event(decision: ResearchApprovalDecision) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:research-approval:{decision.decision_id}",
        event_type="ResearchApprovalDecisionRecorded",
        occurred_at=decision.decided_at,
        actor_ref=decision.actor_ref,
        correlation_id=decision.proposal_id,
        causation_id=decision.decision_id,
        scope="research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"proposal_id": decision.proposal_id, "decision": decision.decision.value, "proposal_hash": decision.proposal_hash},
        evidence_refs=(),
        audit_refs=(),
        appended_at=decision.decided_at,
    )


def record_approval_metrics(metrics: MetricsCollector, decision: ResearchApprovalDecision) -> None:
    if decision.decision is ResearchDecision.APPROVE:
        metrics.increment("gaon_knowledge_approvals_total", component="research")
    elif decision.decision is ResearchDecision.REJECT:
        metrics.increment("gaon_knowledge_rejections_total", component="research")
