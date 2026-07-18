"""Durable research orchestration and reporting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import sqlite3

from gaon.research.evidence import build_evidence_bundle, evidence_from_search
from gaon.research.knowledge import KnowledgeProposal, proposal_from_bundle
from gaon.research.planning import ResearchRequest, deterministic_research_plan
from gaon.research.search import FakeSearchProvider, SearchQuery
from gaon.runtime.event_store import DurableEvent
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.serialization import dumps_json, loads_json


class ResearchRunState(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    COLLECTING = "collecting"
    BUILDING_CONTEXT = "building_context"
    SYNTHESIZING = "synthesizing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    query: str
    status: ResearchRunState
    created_at: str
    updated_at: str
    plan_hash: str | None = None
    failure_reason: str | None = None

    def transition(self, status: ResearchRunState, *, updated_at: str, failure_reason: str | None = None) -> "ResearchRun":
        if self.status in {ResearchRunState.COMPLETED, ResearchRunState.FAILED, ResearchRunState.CANCELLED}:
            raise ValueError("terminal research run cannot transition")
        return replace(self, status=status, updated_at=updated_at, failure_reason=failure_reason)


@dataclass(frozen=True)
class ResearchReport:
    run_id: str
    title: str
    findings: tuple[str, ...]
    citations: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    knowledge_proposals: tuple[str, ...]
    provider_metadata: dict[str, str]
    created_at: str

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", "## Findings", *[f"- {item}" for item in self.findings], "", "## Citations", *[f"- {item}" for item in self.citations]]
        if self.conflicting_evidence:
            lines.extend(["", "## Conflicting Evidence", *[f"- {item}" for item in self.conflicting_evidence]])
        lines.extend(["", "## Risks", *[f"- {item}" for item in self.risks], "", "## Unknowns", *[f"- {item}" for item in self.unknowns]])
        return "\n".join(lines)

    def to_json(self) -> str:
        return dumps_json(
            {
                "run_id": self.run_id,
                "title": self.title,
                "findings": list(self.findings),
                "citations": list(self.citations),
                "conflicting_evidence": list(self.conflicting_evidence),
                "risks": list(self.risks),
                "unknowns": list(self.unknowns),
                "knowledge_proposals": list(self.knowledge_proposals),
                "provider_metadata": self.provider_metadata,
                "created_at": self.created_at,
            }
        )


class SQLiteResearchRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, run: ResearchRun, report: ResearchReport | None = None) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO research_brain_runs(run_id, query, status, plan_hash, report_json, failure_reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, plan_hash = excluded.plan_hash, report_json = excluded.report_json, failure_reason = excluded.failure_reason, updated_at = excluded.updated_at",
                (run.run_id, run.query, run.status.value, run.plan_hash, report.to_json() if report else None, run.failure_reason, run.created_at, run.updated_at),
            )

    def checkpoint(self, run: ResearchRun, payload: dict[str, object]) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO research_brain_checkpoints(run_id, status, checkpoint_json, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, checkpoint_json = excluded.checkpoint_json, updated_at = excluded.updated_at",
                (run.run_id, run.status.value, dumps_json(payload), run.updated_at),
            )

    def get(self, run_id: str) -> ResearchRun:
        row = self._connection.execute("SELECT run_id, query, status, created_at, updated_at, plan_hash, failure_reason FROM research_brain_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return ResearchRun(str(row[0]), str(row[1]), ResearchRunState(str(row[2])), str(row[3]), str(row[4]), str(row[5]) if row[5] else None, str(row[6]) if row[6] else None)

    def report(self, run_id: str) -> ResearchReport:
        row = self._connection.execute("SELECT report_json FROM research_brain_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None or row[0] is None:
            raise KeyError(run_id)
        payload = loads_json(str(row[0]))
        return ResearchReport(
            str(payload["run_id"]),
            str(payload["title"]),
            tuple(payload["findings"]),  # type: ignore[arg-type]
            tuple(payload["citations"]),  # type: ignore[arg-type]
            tuple(payload["conflicting_evidence"]),  # type: ignore[arg-type]
            tuple(payload["risks"]),  # type: ignore[arg-type]
            tuple(payload["unknowns"]),  # type: ignore[arg-type]
            tuple(payload["knowledge_proposals"]),  # type: ignore[arg-type]
            {str(k): str(v) for k, v in payload["provider_metadata"].items()},  # type: ignore[index]
            str(payload["created_at"]),
        )


class ResearchOrchestratorV3:
    def __init__(self, repository: SQLiteResearchRunRepository, *, metrics: MetricsCollector | None = None) -> None:
        self._repository = repository
        self._metrics = metrics or MetricsCollector()

    def run(self, query: str, *, run_id: str, dry_run: bool, now: str = "2026-07-18T00:00:00Z") -> tuple[ResearchRun, ResearchReport]:
        run = ResearchRun(run_id, query, ResearchRunState.CREATED, now, now)
        self._repository.save(run)
        plan = deterministic_research_plan(ResearchRequest(f"req:{run_id}", query, "actor:redacted", now))
        run = run.transition(ResearchRunState.PLANNED, updated_at=now)
        run = replace(run, plan_hash=plan.plan_hash)
        self._repository.save(run)
        self._repository.checkpoint(run, {"plan_hash": plan.plan_hash})
        run = run.transition(ResearchRunState.COLLECTING, updated_at=now)
        results = FakeSearchProvider((("Synthetic evidence", "https://example.com/evidence", f"{query} deterministic evidence"),)).search(SearchQuery(query, "fake"))
        evidence = tuple(evidence_from_search(result, query=query) for result in results)
        run = run.transition(ResearchRunState.BUILDING_CONTEXT, updated_at=now)
        bundle = build_evidence_bundle(evidence)
        run = run.transition(ResearchRunState.SYNTHESIZING, updated_at=now)
        proposal = proposal_from_bundle(f"kp:{run_id}", bundle, claim_statement=f"Research finding for {query}", created_at=now)
        run = run.transition(ResearchRunState.AWAITING_REVIEW, updated_at=now)
        report = _report(run_id, query, bundle, proposal, dry_run=dry_run, now=now)
        self._repository.checkpoint(run, {"status": run.status.value, "citations": [citation.citation_id for citation in bundle.citations]})
        final = run.transition(ResearchRunState.COMPLETED if dry_run else ResearchRunState.AWAITING_REVIEW, updated_at=now)
        self._repository.save(final, report)
        self._metrics.increment("gaon_research_runs_total", component="research")
        return final, report

    def resume(self, run_id: str) -> ResearchRun:
        return self._repository.get(run_id)


def research_run_event(run: ResearchRun) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:research-run:{run.run_id}:{run.status.value}",
        event_type="ResearchRunStateChanged",
        occurred_at=run.updated_at,
        actor_ref="system",
        correlation_id=run.run_id,
        causation_id=None,
        scope="research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"run_id": run.run_id, "status": run.status.value},
        evidence_refs=(),
        audit_refs=(),
        appended_at=run.updated_at,
    )


def _report(run_id: str, query: str, bundle, proposal: KnowledgeProposal, *, dry_run: bool, now: str) -> ResearchReport:
    return ResearchReport(
        run_id=run_id,
        title=f"Research Report: {query}",
        findings=(f"Deterministic evidence collected for: {query}",),
        citations=tuple(f"{citation.citation_id} {citation.url}" for citation in bundle.citations),
        conflicting_evidence=tuple(item.evidence_id for item in bundle.items if item.contradiction),
        risks=("Synthetic dry-run evidence only",),
        unknowns=("No live provider validation performed",),
        knowledge_proposals=(proposal.proposal_id,),
        provider_metadata={"mode": "dry-run" if dry_run else "review"},
        created_at=now,
    )
