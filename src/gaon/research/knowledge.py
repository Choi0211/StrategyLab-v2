"""Evidence-backed knowledge proposals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import sqlite3

from gaon.research.evidence import EvidenceBundle
from gaon.runtime.event_store import DurableEvent
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.serialization import dumps_json, loads_json


class KnowledgeProposalStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class KnowledgeClaim:
    claim_id: str
    statement: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeProposal:
    proposal_id: str
    version: int
    claims: tuple[KnowledgeClaim, ...]
    evidence_refs: tuple[str, ...]
    confidence: float
    status: KnowledgeProposalStatus
    provenance: dict[str, str]
    review_after: str | None
    expires_at: str | None
    proposal_hash: str
    created_at: str
    updated_at: str
    contradictions: tuple[str, ...] = ()

    def next_version(self, *, updated_at: str) -> "KnowledgeProposal":
        return build_knowledge_proposal(
            f"{self.proposal_id}:v{self.version + 1}",
            self.claims,
            self.evidence_refs,
            confidence=self.confidence,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=updated_at,
            version=self.version + 1,
            review_after=self.review_after,
            expires_at=self.expires_at,
            contradictions=self.contradictions,
        )

    def approve_without_workflow(self) -> "KnowledgeProposal":
        raise PermissionError("knowledge proposals cannot be promoted without approval workflow")


def build_knowledge_proposal(
    proposal_id: str,
    claims: tuple[KnowledgeClaim, ...],
    evidence_refs: tuple[str, ...],
    *,
    confidence: float,
    provenance: dict[str, str],
    created_at: str,
    updated_at: str,
    version: int = 1,
    review_after: str | None = None,
    expires_at: str | None = None,
    approved_statements: tuple[str, ...] = (),
    contradictions: tuple[str, ...] = (),
) -> KnowledgeProposal:
    if not claims:
        raise ValueError("knowledge proposal requires at least one claim")
    missing = tuple(claim.claim_id for claim in claims if not claim.evidence_ids)
    detected = tuple(claim.statement for claim in claims if claim.statement in approved_statements)
    status = KnowledgeProposalStatus.INSUFFICIENT_EVIDENCE if missing else KnowledgeProposalStatus.DRAFT
    all_contradictions = tuple(dict.fromkeys((*contradictions, *detected)))
    material = {
        "version": version,
        "claims": [{"claim_id": claim.claim_id, "statement": claim.statement, "evidence_ids": claim.evidence_ids} for claim in claims],
        "evidence_refs": evidence_refs,
        "confidence": confidence,
    }
    proposal_hash = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return KnowledgeProposal(
        proposal_id,
        version,
        claims,
        evidence_refs,
        confidence,
        status,
        dict(provenance),
        review_after,
        expires_at,
        proposal_hash,
        created_at,
        updated_at,
        all_contradictions,
    )


def proposal_from_bundle(proposal_id: str, bundle: EvidenceBundle, *, claim_statement: str, created_at: str) -> KnowledgeProposal:
    evidence_ids = tuple(item.evidence_id for item in bundle.items)
    claim = KnowledgeClaim(f"claim:{proposal_id}:1", claim_statement, evidence_ids)
    confidence = min(0.9, 0.3 + 0.1 * len(evidence_ids))
    return build_knowledge_proposal(
        proposal_id,
        (claim,),
        evidence_ids,
        confidence=confidence,
        provenance={"source": "research_evidence_bundle"},
        created_at=created_at,
        updated_at=created_at,
        contradictions=tuple(item.evidence_id for item in bundle.items if item.contradiction),
    )


class SQLiteKnowledgeProposalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, proposal: KnowledgeProposal) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO knowledge_proposals(
                    proposal_id, version, proposal_hash, status, confidence, claims_json, evidence_refs_json,
                    provenance_json, review_after, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _proposal_row(proposal),
            )

    def get(self, proposal_id: str) -> KnowledgeProposal:
        row = self._connection.execute("SELECT * FROM knowledge_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return _proposal_from_row(row)


def proposal_event(proposal: KnowledgeProposal, *, occurred_at: str) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:knowledge-proposal:{proposal.proposal_id}",
        event_type="KnowledgeProposalCreated",
        occurred_at=occurred_at,
        actor_ref="system",
        correlation_id=proposal.proposal_id,
        causation_id=None,
        scope="research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"proposal_id": proposal.proposal_id, "status": proposal.status.value, "proposal_hash": proposal.proposal_hash},
        evidence_refs=proposal.evidence_refs,
        audit_refs=(),
        appended_at=occurred_at,
    )


def record_proposal_metrics(metrics: MetricsCollector, proposal: KnowledgeProposal) -> None:
    metrics.increment("gaon_knowledge_proposals_total", status=proposal.status.value)


def _proposal_row(proposal: KnowledgeProposal) -> tuple[object, ...]:
    return (
        proposal.proposal_id,
        proposal.version,
        proposal.proposal_hash,
        proposal.status.value,
        proposal.confidence,
        dumps_json({"claims": [claim.__dict__ for claim in proposal.claims]}),
        json.dumps(list(proposal.evidence_refs), sort_keys=True),
        dumps_json(proposal.provenance),
        proposal.review_after,
        proposal.expires_at,
        proposal.created_at,
        proposal.updated_at,
    )


def _proposal_from_row(row: tuple[object, ...]) -> KnowledgeProposal:
    claims_payload = loads_json(str(row[5]))
    claims = tuple(KnowledgeClaim(str(item["claim_id"]), str(item["statement"]), tuple(item["evidence_ids"])) for item in claims_payload["claims"])  # type: ignore[index]
    return KnowledgeProposal(
        proposal_id=str(row[0]),
        version=int(row[1]),
        proposal_hash=str(row[2]),
        status=KnowledgeProposalStatus(str(row[3])),
        confidence=float(row[4]),
        claims=claims,
        evidence_refs=tuple(json.loads(str(row[6]))),
        provenance={str(k): str(v) for k, v in loads_json(str(row[7])).items()},
        review_after=str(row[8]) if row[8] is not None else None,
        expires_at=str(row[9]) if row[9] is not None else None,
        created_at=str(row[10]),
        updated_at=str(row[11]),
    )
