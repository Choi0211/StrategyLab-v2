"""Daily Research pipeline on top of scheduled automation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import sqlite3

from gaon.research.evidence import build_evidence_bundle, evidence_from_search
from gaon.research.knowledge import KnowledgeProposalStatus, SQLiteKnowledgeProposalRepository, proposal_from_bundle
from gaon.research.planning import ResearchRequest, deterministic_research_plan
from gaon.research.search import FakeSearchProvider, SearchQuery
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, ToolSelection
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledJob, ScheduledJobRepository, ScheduledRunStatus, _validate_utc
from gaon.runtime.serialization import dumps_json, loads_json


class DailyResearchRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DailyResearchTopic:
    topic_id: str
    name: str
    query: str


@dataclass(frozen=True)
class DailyResearchProfile:
    profile_id: str
    topic: str
    query: str
    enabled: bool
    priority: int
    source_preferences: tuple[str, ...]
    time_range: str
    language: str
    created_at: str
    updated_at: str
    metadata: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.profile_id or not self.topic.strip() or not self.query.strip():
            raise ValueError("daily research profile requires id, topic, and query")
        if self.priority < 0 or self.priority > 100:
            raise ValueError("daily research profile priority must be between 0 and 100")
        _validate_utc(self.created_at)
        _validate_utc(self.updated_at)


@dataclass(frozen=True)
class DailyResearchResult:
    title: str
    generated_at: str
    topic: str
    executive_summary: str
    key_findings: tuple[str, ...]
    citations: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    knowledge_proposals: tuple[str, ...]
    provider_metadata: dict[str, str]

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"Generated: {self.generated_at}",
            f"Topic: {self.topic}",
            "",
            "## Executive Summary",
            self.executive_summary,
            "",
            "## Key Findings",
            *[f"- {item}" for item in self.key_findings],
            "",
            "## Evidence and Citations",
            *[f"- {item}" for item in self.citations],
            "",
            "## Risks",
            *[f"- {item}" for item in self.risks],
            "",
            "## Unknowns",
            *[f"- {item}" for item in self.unknowns],
            "",
            "## Knowledge Proposals",
            *[f"- {item}" for item in self.knowledge_proposals],
        ]
        if self.conflicting_evidence:
            lines.extend(["", "## Conflicting Evidence", *[f"- {item}" for item in self.conflicting_evidence]])
        return "\n".join(lines)

    def to_json(self) -> str:
        return dumps_json(
            {
                "title": self.title,
                "generated_at": self.generated_at,
                "topic": self.topic,
                "executive_summary": self.executive_summary,
                "key_findings": list(self.key_findings),
                "citations": list(self.citations),
                "conflicting_evidence": list(self.conflicting_evidence),
                "risks": list(self.risks),
                "unknowns": list(self.unknowns),
                "knowledge_proposals": list(self.knowledge_proposals),
                "provider_metadata": self.provider_metadata,
            }
        )


@dataclass(frozen=True)
class DailyResearchRun:
    run_id: str
    profile_id: str
    status: DailyResearchRunStatus
    started_at: str
    completed_at: str | None
    result: DailyResearchResult | None
    proposal_ids: tuple[str, ...]
    error: str | None = None


class DailyResearchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create_profile(self, profile: DailyResearchProfile) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO daily_research_profiles(
                        profile_id, topic, query, enabled, priority, source_preferences_json,
                        time_range, language, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _profile_row(profile),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"duplicate daily research profile id: {profile.profile_id}") from exc

    def get_profile(self, profile_id: str) -> DailyResearchProfile:
        row = self._connection.execute(
            """
            SELECT profile_id, topic, query, enabled, priority, source_preferences_json,
                   time_range, language, metadata_json, created_at, updated_at
              FROM daily_research_profiles WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            raise KeyError(profile_id)
        return _profile_from_row(row)

    def list_profiles(self) -> tuple[DailyResearchProfile, ...]:
        rows = self._connection.execute(
            """
            SELECT profile_id, topic, query, enabled, priority, source_preferences_json,
                   time_range, language, metadata_json, created_at, updated_at
              FROM daily_research_profiles ORDER BY priority DESC, profile_id
            """
        ).fetchall()
        return tuple(_profile_from_row(row) for row in rows)

    def set_enabled(self, profile_id: str, enabled: bool, *, updated_at: str) -> DailyResearchProfile:
        _validate_utc(updated_at)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE daily_research_profiles SET enabled = ?, updated_at = ? WHERE profile_id = ?",
                (1 if enabled else 0, updated_at, profile_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(profile_id)
        return self.get_profile(profile_id)

    def start_run(self, profile_id: str, *, started_at: str) -> DailyResearchRun | None:
        _validate_utc(started_at)
        run = DailyResearchRun(_run_id(profile_id, started_at), profile_id, DailyResearchRunStatus.RUNNING, started_at, None, None, ())
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO daily_research_runs(run_id, profile_id, status, started_at, completed_at, report_json, proposal_ids_json, error)
                    VALUES (?, ?, ?, ?, NULL, ?, ?, NULL)
                    """,
                    (run.run_id, run.profile_id, run.status.value, run.started_at, "{}", json.dumps([])),
                )
            return run
        except sqlite3.IntegrityError:
            return None

    def complete_run(
        self,
        run: DailyResearchRun,
        status: DailyResearchRunStatus,
        *,
        completed_at: str,
        result: DailyResearchResult | None,
        proposal_ids: tuple[str, ...] = (),
        error: str | None = None,
    ) -> DailyResearchRun:
        _validate_utc(completed_at)
        completed = DailyResearchRun(run.run_id, run.profile_id, status, run.started_at, completed_at, result, proposal_ids, error)
        with self._connection:
            self._connection.execute(
                "UPDATE daily_research_runs SET status = ?, completed_at = ?, report_json = ?, proposal_ids_json = ?, error = ? WHERE run_id = ?",
                (status.value, completed_at, result.to_json() if result else "{}", json.dumps(list(proposal_ids), sort_keys=True), error, run.run_id),
            )
        return completed

    def list_runs(self, profile_id: str | None = None) -> tuple[DailyResearchRun, ...]:
        if profile_id is None:
            rows = self._connection.execute("SELECT run_id, profile_id, status, started_at, completed_at, report_json, proposal_ids_json, error FROM daily_research_runs ORDER BY started_at, run_id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT run_id, profile_id, status, started_at, completed_at, report_json, proposal_ids_json, error FROM daily_research_runs WHERE profile_id = ? ORDER BY started_at, run_id",
                (profile_id,),
            ).fetchall()
        return tuple(_run_from_row(row) for row in rows)


class DailyResearchPipeline:
    def __init__(
        self,
        repository: DailyResearchRepository,
        scheduled_repository: ScheduledJobRepository,
        config: GaonRuntimeConfig,
        *,
        metrics: MetricsCollector | None = None,
        event_store: SQLiteEventStore | None = None,
    ) -> None:
        self._repository = repository
        self._scheduled_repository = scheduled_repository
        self._config = config
        self._metrics = metrics or MetricsCollector()
        self._event_store = event_store

    def schedule_profile(self, profile: DailyResearchProfile, *, next_run_at: str) -> ScheduledJob:
        job = ScheduledJob(
            f"daily-research:{profile.profile_id}",
            f"Daily Research: {profile.topic}",
            profile.query,
            ScheduleDefinition("UTC", next_run_at, "daily"),
            profile.enabled,
            profile.created_at,
            profile.updated_at,
            agent_selection=AgentSelection.RESEARCH_BRAIN,
            tool_constraints=(ToolSelection.RESEARCH_PLANNER, ToolSelection.EVIDENCE_SEARCH, ToolSelection.KNOWLEDGE_PROPOSAL),
            metadata={"kind": "daily_research", "profile_id": profile.profile_id},
            max_attempts=2,
        )
        self._scheduled_repository.create(job)
        return job

    def run_due(self, *, now: str) -> tuple[DailyResearchRun, ...]:
        runs: list[DailyResearchRun] = []
        for job in self._scheduled_repository.due(now):
            if (job.metadata or {}).get("kind") != "daily_research":
                continue
            scheduled_run = self._scheduled_repository.claim_run(job, now=now)
            if scheduled_run is None:
                continue
            profile_id = (job.metadata or {}).get("profile_id", "")
            try:
                profile = self._repository.get_profile(profile_id)
                if not profile.enabled:
                    self._scheduled_repository.complete_run(scheduled_run, ScheduledRunStatus.SKIPPED, completed_at=now, result={"reason": "profile disabled"})
                    continue
                daily_run = self.run_profile(profile.profile_id, now=now)
                scheduled_status = ScheduledRunStatus.SUCCEEDED if daily_run.status == DailyResearchRunStatus.COMPLETED else ScheduledRunStatus.FAILED
                self._scheduled_repository.complete_run(scheduled_run, scheduled_status, completed_at=now, result={"daily_run_id": daily_run.run_id, "status": daily_run.status.value}, error=daily_run.error)
                runs.append(daily_run)
            except Exception as exc:  # noqa: BLE001 - due execution failure is isolated.
                self._scheduled_repository.complete_run(scheduled_run, ScheduledRunStatus.FAILED, completed_at=now, result={}, error=exc.__class__.__name__)
        return tuple(runs)

    def run_profile(self, profile_id: str, *, now: str) -> DailyResearchRun:
        profile = self._repository.get_profile(profile_id)
        run = self._repository.start_run(profile.profile_id, started_at=now)
        if run is None:
            return self._repository.list_runs(profile.profile_id)[-1]
        self._record(daily_research_event("DailyResearchRunStarted", profile, run, now))
        if not profile.enabled:
            completed = self._repository.complete_run(run, DailyResearchRunStatus.SKIPPED, completed_at=now, result=None, error="profile disabled")
            self._record(daily_research_event("DailyResearchRunBlocked", profile, completed, now))
            self._metrics.increment("gaon_daily_research_blocked_total", component="daily_research")
            return completed
        try:
            if "fail" in profile.query.lower():
                raise RuntimeError("synthetic daily research failure")
            result = _build_daily_research(profile, run.run_id, now)
            persist_pending_daily_proposal(self._repository._connection, result, run_id=run.run_id, now=now)
            proposal_ids = result.knowledge_proposals
            completed = self._repository.complete_run(run, DailyResearchRunStatus.COMPLETED, completed_at=now, result=result, proposal_ids=proposal_ids)
            self._metrics.increment("gaon_daily_research_runs_total", component="daily_research")
            self._metrics.increment("gaon_daily_research_reports_total", component="daily_research")
            self._metrics.increment("gaon_daily_research_proposals_total", amount=float(len(proposal_ids)), component="daily_research")
            self._record(daily_research_event("DailyResearchRunCompleted", profile, completed, now))
            return completed
        except Exception as exc:  # noqa: BLE001
            completed = self._repository.complete_run(run, DailyResearchRunStatus.FAILED, completed_at=now, result=None, error=exc.__class__.__name__)
            self._metrics.increment("gaon_daily_research_failures_total", component="daily_research")
            self._record(daily_research_event("DailyResearchRunFailed", profile, completed, now))
            return completed

    def _record(self, event: DurableEvent) -> None:
        if self._event_store is not None:
            self._event_store.append(event)


def daily_research_event(event_type: str, profile: DailyResearchProfile, run: DailyResearchRun | None, occurred_at: str) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:daily-research:{event_type}:{profile.profile_id}:{run.run_id if run else occurred_at}",
        event_type=event_type,
        occurred_at=occurred_at,
        actor_ref="scheduler",
        correlation_id=run.run_id if run else profile.profile_id,
        causation_id=profile.profile_id,
        scope="daily_research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"profile_id": profile.profile_id, "run_id": run.run_id if run else "", "status": run.status.value if run else "", "topic": profile.topic},
        evidence_refs=(),
        audit_refs=(),
        appended_at=occurred_at,
    )


def record_daily_research_profile_metric(metrics: MetricsCollector, repository: DailyResearchRepository) -> None:
    metrics.gauge("gaon_daily_research_profiles_total", float(len(repository.list_profiles())), component="daily_research")


def _build_daily_research(profile: DailyResearchProfile, run_id: str, now: str) -> DailyResearchResult:
    deterministic_research_plan(ResearchRequest(f"daily:{run_id}", profile.query, "scheduler", now))
    rows = tuple(
        (
            f"{profile.topic} source {index}",
            f"https://example.com/{profile.profile_id}/{index}",
            f"{profile.query} deterministic daily research evidence {index}",
        )
        for index in range(1, 4)
    )
    results = FakeSearchProvider(rows).search(SearchQuery(profile.query, "daily-fake", max_results=3, max_content_chars=600))
    evidence = tuple(evidence_from_search(result, query=profile.query) for result in results)
    bundle = build_evidence_bundle(evidence, context_budget_chars=1200)
    proposal = proposal_from_bundle(f"daily-kp:{run_id}", bundle, claim_statement=f"Daily research finding for {profile.topic}", created_at=now)
    proposal = replace(proposal, status=KnowledgeProposalStatus.PENDING_REVIEW)
    # The proposal remains pending review; no trusted-knowledge promotion is performed.
    return DailyResearchResult(
        title=f"Daily Research: {profile.topic}",
        generated_at=now,
        topic=profile.topic,
        executive_summary=f"Deterministic daily research summary for {profile.topic}.",
        key_findings=tuple(f"{citation.citation_id}: {citation.title}" for citation in bundle.citations),
        citations=tuple(f"{citation.citation_id} {citation.url}" for citation in bundle.citations),
        conflicting_evidence=tuple(item.evidence_id for item in bundle.items if item.contradiction),
        risks=("Synthetic deterministic evidence only",),
        unknowns=("No live provider validation performed",),
        knowledge_proposals=(proposal.proposal_id,),
        provider_metadata={"provider": "fake", "mode": "free_only", "proposal_status": proposal.status.value},
    )


def persist_pending_daily_proposal(connection: sqlite3.Connection, result: DailyResearchResult, *, run_id: str, now: str) -> None:
    if not result.knowledge_proposals:
        return
    # Rebuild a minimal pending-review proposal tied to the report so repository behavior is exercised durably.
    rows = (("Daily report", f"https://example.com/report/{run_id}", result.executive_summary),)
    search_result = FakeSearchProvider(rows).search(SearchQuery(result.topic, "daily-report", max_results=1))[0]
    bundle = build_evidence_bundle((evidence_from_search(search_result, query=result.topic),), context_budget_chars=600)
    proposal = replace(proposal_from_bundle(result.knowledge_proposals[0], bundle, claim_statement=result.executive_summary, created_at=now), status=KnowledgeProposalStatus.PENDING_REVIEW)
    SQLiteKnowledgeProposalRepository(connection).add(proposal)


def _profile_row(profile: DailyResearchProfile) -> tuple[object, ...]:
    return (
        profile.profile_id,
        profile.topic,
        profile.query,
        1 if profile.enabled else 0,
        profile.priority,
        json.dumps(list(profile.source_preferences), sort_keys=True),
        profile.time_range,
        profile.language,
        dumps_json(profile.metadata or {}),
        profile.created_at,
        profile.updated_at,
    )


def _profile_from_row(row: tuple[object, ...]) -> DailyResearchProfile:
    return DailyResearchProfile(
        str(row[0]),
        str(row[1]),
        str(row[2]),
        bool(row[3]),
        int(row[4]),
        tuple(str(item) for item in json.loads(str(row[5]))),
        str(row[6]),
        str(row[7]),
        str(row[9]),
        str(row[10]),
        {str(k): str(v) for k, v in loads_json(str(row[8])).items()},
    )


def _run_from_row(row: tuple[object, ...]) -> DailyResearchRun:
    report_payload = loads_json(str(row[5]))
    result = _result_from_payload(report_payload) if report_payload else None
    return DailyResearchRun(
        str(row[0]),
        str(row[1]),
        DailyResearchRunStatus(str(row[2])),
        str(row[3]),
        str(row[4]) if row[4] is not None else None,
        result,
        tuple(str(item) for item in json.loads(str(row[6]))),
        str(row[7]) if row[7] is not None else None,
    )


def _result_from_payload(payload: dict[str, object]) -> DailyResearchResult | None:
    if not payload:
        return None
    return DailyResearchResult(
        str(payload["title"]),
        str(payload["generated_at"]),
        str(payload["topic"]),
        str(payload["executive_summary"]),
        tuple(str(item) for item in payload["key_findings"]),  # type: ignore[index]
        tuple(str(item) for item in payload["citations"]),  # type: ignore[index]
        tuple(str(item) for item in payload["conflicting_evidence"]),  # type: ignore[index]
        tuple(str(item) for item in payload["risks"]),  # type: ignore[index]
        tuple(str(item) for item in payload["unknowns"]),  # type: ignore[index]
        tuple(str(item) for item in payload["knowledge_proposals"]),  # type: ignore[index]
        {str(k): str(v) for k, v in payload["provider_metadata"].items()},  # type: ignore[index]
    )


def _run_id(profile_id: str, now: str) -> str:
    return f"daily-research-run:{profile_id}:{now}"
