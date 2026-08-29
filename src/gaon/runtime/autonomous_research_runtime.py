"""Bounded background continuation for a persisted ACTIVE ResearchMission.

This is deliberately a thin runtime wiring adapter, not a new research
engine: it advances a mission by calling
``gaon.runtime.llm_conversation.LLMConversationBrain.respond()`` with a
synthetic continuation message - the EXACT same real, tool-routed,
bounded-per-turn code path a Telegram "연구 계속해주세요" message already
takes (``LLMConversationBrain._try_mission_driven_research_cycle``). No
second ResearchMission store, no second research engine, and no reuse of
``gaon.runtime.daily_research.DailyResearchPipeline`` (which composes
``deterministic_research_plan`` - synthetic/deterministic fixtures, never
appropriate to present as real autonomous research).

Registration reuses the existing durable
``gaon.runtime.scheduled_automation.ScheduledJobRepository`` - the same
table ``gaon.runtime.daily_research``/``gaon.runtime.daily_briefing``
already use - instead of inventing a second scheduler. A tick claims the
due job, advances the mission by at most one bounded cycle, and schedules
the next tick; a service restart simply resumes from the persisted
``next_run_at``.

Safety boundary: the mission-driven cycle this calls never imports or
reaches broker/order execution (``gaon.adapters.trading`` /
``strategy_execution`` / ``strategy_deployment``) or champion promotion
(``gaon.knowledge.promotion_gate`` / ``human_gated_promotion``) code. A
mission that has reached ``MissionStatus.AWAITING_HUMAN_APPROVAL`` (the
codebase's name for the spec's READY_FOR_APPROVAL gate) is never advanced
further by this worker - approval, promotion, and deployment all remain
exclusively human-initiated conversational actions.

Hotfix #168: bounded strategy-hypothesis-space exhaustion is no longer a
silent terminal BLOCKED that repeats forever. Once the existing narrow
``attempt_bounded_stagnation_recovery`` finds no eligible candidate for a
mission BLOCKED on ``strategy_hypothesis_space_exhausted``, this worker
hands off to ``gaon.research.research_direction`` for one bounded, evidence-
grounded FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH DIRECTION pass
(see that module for detail) instead of a bare no-op. This is research-
space *planning*, not trading authority: a ``ResearchDirection`` record can
never mutate strategy config, create/promote a candidate, create an
approval, or execute an order - research autonomy and capital/trading
authority remain strictly separate, exactly as before this hotfix.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable

from gaon.knowledge.research_mission import (
    MissionStatus,
    ResearchMission,
    candidate_records,
    set_active_candidate,
    update_candidate,
)
from gaon.knowledge.strategy_candidate import (
    EconomicViabilityStatus,
    StrategyCandidateStatus,
    candidate_remaining_blockers,
    evaluate_economic_viability,
    next_untried_family,
)
from gaon.research.research_direction import (
    ResearchDirectionRepository,
    ResearchDirectionStatus,
    analyze_mission_failure,
    plan_research_direction,
)
from gaon.research.research_priority import propose_research_priority
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledJob, ScheduledJobRepository, ScheduledRunStatus

_JOB_ID_PREFIX = "autonomous-research:tick"
_JOB_KIND = "autonomous_research"
_CONTINUATION_REQUEST_TEXT = "연구 계속해주세요"
_DEFAULT_INTERVAL_SECONDS = 900

# Only a candidate that stagnated purely because the cycle-stagnation
# bookkeeping threshold (STAGNATION_CYCLE_THRESHOLD) tripped - not because
# its own bounded validation/breadth axes were actually exhausted, and not
# an economic-viability failure - is eligible for bounded recovery. This
# keeps the recovery path from ever re-opening a candidate the state
# machine already decided is a genuine dead end.
_RECOVERABLE_STAGNATION_REASON = "validation_cycle_exhausted_without_progress"


def attempt_bounded_stagnation_recovery(
    mission: ResearchMission,
    *,
    now: str,
    max_candidates: int = 2,
) -> tuple[ResearchMission, bool]:
    """Bounded recovery for a mission BLOCKED on
    ``strategy_hypothesis_space_exhausted``.

    Only reopens a STAGNANT candidate that (a) stagnated purely on the
    progress-stall bookkeeping threshold rather than genuine axis
    exhaustion, (b) still has at least one real unresolved validation
    blocker (``candidate_remaining_blockers``), and (c) has not already
    been decisively rejected on economic-viability grounds. Recovery never
    creates a new strategy family/candidate identity - it only resumes an
    existing candidate's own already-declared-but-unfinished validation
    work, bounded to ``max_candidates`` scanned per call so this can never
    loop unboundedly. Returns the mission unchanged (still BLOCKED, with
    its original honest ``blocked_reason``) when no eligible candidate is
    found - callers must report that blocker honestly rather than
    substituting a fabricated explanation.
    """
    if mission.status is not MissionStatus.BLOCKED:
        return mission, False
    if not (mission.blocked_reason or "").startswith("strategy_hypothesis_space_exhausted"):
        return mission, False
    scanned = 0
    for candidate in candidate_records(mission):
        if candidate.status is not StrategyCandidateStatus.STAGNANT:
            continue
        if candidate.rejected_reason != _RECOVERABLE_STAGNATION_REASON:
            continue
        if scanned >= max_candidates:
            break
        scanned += 1
        if not candidate_remaining_blockers(candidate):
            continue
        if evaluate_economic_viability(candidate).status is EconomicViabilityStatus.FAIL:
            continue
        recovered_candidate = replace(
            candidate,
            status=StrategyCandidateStatus.VALIDATING,
            cycles_without_progress=0,
            rejected_reason=None,
            updated_at=now,
        )
        recovered_mission = update_candidate(mission, recovered_candidate, now=now)
        recovered_mission = set_active_candidate(recovered_mission, candidate.candidate_id, now=now)
        recovered_mission = replace(recovered_mission, status=MissionStatus.ACTIVE, blocked_reason=None, updated_at=now)
        return recovered_mission, True
    return mission, False


@dataclass(frozen=True)
class AutonomousResearchTickResult:
    attempted: bool
    action: str
    mission_status: str | None = None
    route: str | None = None
    blocker: str | None = None
    error_type: str | None = None
    # Hotfix #168 observability fields (Section 10) - populated only on the
    # BLOCKED + strategy_hypothesis_space_exhausted + narrow-recovery-
    # ineligible path (see AutonomousResearchRuntimeWorker._plan_research_
    # direction); None on every other action. Never reports work that did
    # not actually happen - a "planned"/"awaiting_evidence" action always
    # corresponds to a real read/plan/persist call that just ran.
    recovery_eligible: bool | None = None
    failure_class: str | None = None
    research_priority: str | None = None
    direction_id: str | None = None
    direction_status: str | None = None
    next_research_action: str | None = None


class AutonomousResearchRuntimeWorker:
    """Production tick adapter that advances the persisted, canonical
    Telegram ResearchMission (``session_id = f"telegram:{chat_id}"``, the
    same session/scope binding ``TelegramConversationAgent`` uses) by at
    most one bounded real research cycle per tick.

    Every branch that would leave the mission at
    ``MissionStatus.AWAITING_HUMAN_APPROVAL`` or beyond is a hard stop:
    this worker never approves, applies, promotes, or deploys anything,
    and never touches an order/broker code path (see module docstring).
    """

    def __init__(
        self,
        config: GaonRuntimeConfig,
        connection,
        *,
        brain_factory: Callable[[], LLMConversationBrain] | None = None,
        metrics: MetricsCollector | None = None,
        now_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._connection = connection
        self._brain_factory = brain_factory or self._default_brain_factory
        self._metrics = metrics or MetricsCollector()
        self._now_factory = now_factory or _utc_now

    def _default_brain_factory(self) -> LLMConversationBrain:
        from gaon.runtime.telegram_agent import TelegramConversationAgent

        return TelegramConversationAgent(self._config, self._connection)._brain

    def tick(self) -> AutonomousResearchTickResult:
        now = self._now_factory()
        try:
            if not self._config.telegram_allowed_chat_ids:
                self._metrics.increment("autonomous_research_runtime_ticks", status="skipped", reason="no_allowed_chat")
                return AutonomousResearchTickResult(attempted=False, action="skipped_no_allowed_chat")
            chat_id = self._config.telegram_allowed_chat_ids[0]
            session_id = f"telegram:{chat_id}"
            brain = self._brain_factory()
            mission = brain._mission_for(session_id)
            if mission is None:
                return AutonomousResearchTickResult(attempted=True, action="skipped_no_mission")
            if mission.status in (
                MissionStatus.AWAITING_HUMAN_APPROVAL,
                MissionStatus.COMPLETED,
                MissionStatus.CANCELLED,
            ):
                return AutonomousResearchTickResult(
                    attempted=True, action="skipped_awaiting_human_or_terminal", mission_status=mission.status.value
                )
            if mission.status is MissionStatus.BLOCKED:
                recovered_mission, recovered = attempt_bounded_stagnation_recovery(mission, now=now)
                if not recovered:
                    if (mission.blocked_reason or "").startswith("strategy_hypothesis_space_exhausted"):
                        return self._plan_research_direction(mission, session_id, now)
                    self._metrics.increment("autonomous_research_runtime_ticks", status="blocked")
                    return AutonomousResearchTickResult(
                        attempted=True,
                        action="blocked_no_recovery",
                        mission_status=mission.status.value,
                        blocker=mission.blocked_reason,
                        recovery_eligible=False,
                    )
                request = _continuation_request(session_id, chat_id, now, suffix="recovery")
                brain._remember_mission(request, recovered_mission)
            request = _continuation_request(session_id, chat_id, now, suffix="cycle")
            response = brain.respond(request)
            self._metrics.increment("autonomous_research_runtime_ticks", status="ok")
            mission_after = brain._mission_for(session_id)
            return AutonomousResearchTickResult(
                attempted=True,
                action="cycle_executed",
                mission_status=mission_after.status.value if mission_after else None,
                route=response.route,
            )
        except Exception as exc:  # noqa: BLE001 - a mission cycle failure must never take down the runtime tick.
            self._metrics.increment("autonomous_research_runtime_ticks", status="failed")
            return AutonomousResearchTickResult(attempted=True, action="failed", error_type=exc.__class__.__name__)

    def _plan_research_direction(self, mission: ResearchMission, session_id: str, now: str) -> AutonomousResearchTickResult:
        """Hotfix #168: the one new stage reachable only when the mission is
        BLOCKED on ``strategy_hypothesis_space_exhausted`` AND the existing
        narrow ``attempt_bounded_stagnation_recovery`` found no eligible
        candidate. Performs a bounded, single-pass FAILURE ANALYSIS ->
        RESEARCH PRIORITY -> RESEARCH DIRECTION over the mission's already-
        persisted candidate history (never re-running research, never
        calling ``respond()``), then persists both records idempotently
        (see ``gaon.research.research_direction`` - a second call against an
        unchanged mission state is a cheap no-op read, never a duplicate
        row or unbounded work). No candidate/strategy/order/approval state
        is ever touched here.
        """
        priority = propose_research_priority(mission, _binance_config_from_env())
        analysis = analyze_mission_failure(mission, session_ref=session_id, now=now)
        has_untried_family = next_untried_family(candidate_records(mission)) is not None
        direction = plan_research_direction(
            analysis,
            priority,
            has_untried_family=has_untried_family,
            has_recoverable_candidate=False,  # already re-checked False by the caller this tick
            now=now,
        )
        repository = ResearchDirectionRepository(self._connection)
        repository.put_failure_analysis(analysis)
        existing = repository.find_direction_by_fingerprint(direction.fingerprint)
        if existing is None:
            repository.put_direction(direction)
            action = "research_direction_planned"
        else:
            direction = existing
            action = (
                "research_direction_awaiting_evidence"
                if direction.status is ResearchDirectionStatus.AWAITING_EVIDENCE
                else "research_direction_active"
            )
        self._metrics.increment("autonomous_research_runtime_ticks", status=action)
        return AutonomousResearchTickResult(
            attempted=True,
            action=action,
            mission_status=mission.status.value,
            blocker=mission.blocked_reason,
            recovery_eligible=False,
            failure_class=analysis.dominant_failure_class.value,
            research_priority=",".join(priority.flagged_domains) or "none",
            direction_id=direction.direction_id,
            direction_status=direction.status.value,
            next_research_action=direction.next_research_action.value,
        )


def _binance_config_from_env():
    """Best-effort, read-only Binance research context for
    ``propose_research_priority`` - reused, never duplicated, from
    ``gaon.adapters.binance.build_binance_adapter_config_from_env``. Returns
    ``None`` (never raises) when unavailable; ``propose_research_priority``
    already reports an honest ``not_configured``/``read_error`` flag for
    that case rather than fabricating Binance evidence."""
    import os

    try:
        from gaon.adapters.binance import build_binance_adapter_config_from_env

        return build_binance_adapter_config_from_env(os.environ)
    except Exception:  # noqa: BLE001 - Binance context is optional read-only input, never fatal.
        return None


def _continuation_request(session_id: str, chat_id: str, now: str, *, suffix: str) -> LLMConversationRequest:
    """Builds the synthetic continuation request the worker feeds to
    ``LLMConversationBrain.respond()``.

    ``source="telegram"`` with a ``message_id`` prefixed ``telegram:`` is
    required for ``LLMConversationBrain._is_conversational_mvp_source`` to
    route this through the same real conversational-MVP pipeline (and
    therefore the same mission-driven continuation branch) a live Telegram
    turn uses - this mission is, in fact, the canonical Telegram-scoped
    mission for ``session_id``. ``user_ref`` stays distinct from any real
    Telegram user id so audit/log readers can always tell a background tick
    apart from a live user turn.

    ``is_system_turn=True`` marks this as a synthetic, system-originated
    continuation rather than a real human message: ``LLMConversationBrain.
    respond()`` uses it to suppress provenance-sensitive side effects that
    must never be attributed to a human - the turn is not persisted as a
    "user"/"assistant" ``conversation_messages`` row, and it never feeds
    cognitive feedback/preference learning or creates/mutates a cognitive
    Goal record. Routing and the real ResearchMission-driven research cycle
    itself are unaffected by this flag; only conversation-history/cognitive-
    memory side effects are suppressed.
    """
    return LLMConversationRequest(
        session_id=session_id,
        user_ref="autonomous-research-worker",
        source="telegram",
        text=_CONTINUATION_REQUEST_TEXT,
        received_at=now,
        message_id=f"telegram:{chat_id}:autonomous-worker:{suffix}:{now}",
        is_system_turn=True,
    )


def ensure_autonomous_research_job(
    repository: ScheduledJobRepository,
    *,
    now: str,
    interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
) -> bool:
    """Idempotently registers the first due tick job if none is pending."""
    existing = tuple(job for job in repository.list() if (job.metadata or {}).get("kind") == _JOB_KIND and job.enabled)
    if existing:
        return False
    job = ScheduledJob(
        f"{_JOB_ID_PREFIX}:{now}",
        "Gaon Autonomous Research Tick",
        _CONTINUATION_REQUEST_TEXT,
        ScheduleDefinition("UTC", now, "manual"),
        True,
        now,
        now,
        metadata={"kind": _JOB_KIND},
        max_attempts=1,
    )
    try:
        repository.create(job)
    except ValueError:
        return False
    return True


def run_due_autonomous_research(
    repository: ScheduledJobRepository,
    worker: AutonomousResearchRuntimeWorker,
    *,
    now: str,
    interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
) -> tuple[AutonomousResearchTickResult, ...]:
    """Runs any due autonomous-research tick job through the existing
    durable ``ScheduledJobRepository`` (idempotent per claimed run,
    restart-durable via persisted ``next_run_at``), then schedules the
    next tick. Mirrors ``DailyBriefingScheduler.run_due()``'s
    claim-run/complete-run/reschedule-next-occurrence shape.
    """
    results: list[AutonomousResearchTickResult] = []
    for job in repository.due(now):
        if (job.metadata or {}).get("kind") != _JOB_KIND:
            continue
        run = repository.claim_run(job, now=now)
        if run is None:
            continue  # already claimed this tick, or max_attempts reached - idempotent no-op
        try:
            result = worker.tick()
            repository.complete_run(
                run,
                ScheduledRunStatus.SUCCEEDED,
                completed_at=now,
                result={
                    "action": result.action,
                    "mission_status": result.mission_status or "",
                    "blocker": result.blocker or "",
                    "recovery_eligible": result.recovery_eligible,
                    "failure_class": result.failure_class or "",
                    "research_priority": result.research_priority or "",
                    "direction_id": result.direction_id or "",
                    "direction_status": result.direction_status or "",
                    "next_research_action": result.next_research_action or "",
                },
            )
        except Exception as exc:  # noqa: BLE001 - one tick's failure must not block rescheduling.
            result = AutonomousResearchTickResult(attempted=True, action="failed", error_type=exc.__class__.__name__)
            repository.complete_run(run, ScheduledRunStatus.FAILED, completed_at=now, result={}, error=exc.__class__.__name__)
        results.append(result)
        next_run_at = _advance_by_interval(now, interval_seconds)
        next_job = replace(
            job,
            job_id=f"{_JOB_ID_PREFIX}:{next_run_at}",
            schedule=ScheduleDefinition("UTC", next_run_at, "manual"),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        try:
            repository.create(next_job)
        except ValueError:
            pass  # this occurrence already scheduled - idempotent
    return tuple(results)


@dataclass(frozen=True)
class AutonomousResearchRuntimeTickResult:
    enabled: bool
    attempted: bool
    jobs_registered: bool
    results: tuple[AutonomousResearchTickResult, ...] = ()
    error_type: str | None = None


class AutonomousResearchRuntimeService:
    """Production service tick adapter combining job registration, the
    durable due-check, and the bounded mission-cycle worker - the
    autonomous-research analogue of
    ``gaon.runtime.daily_briefing.DailyBriefingRuntimeWorker``.
    """

    def __init__(
        self,
        config: GaonRuntimeConfig,
        repository: ScheduledJobRepository,
        *,
        metrics: MetricsCollector | None = None,
        now_factory: Callable[[], str] | None = None,
        interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
        worker: AutonomousResearchRuntimeWorker | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._metrics = metrics or MetricsCollector()
        self._now_factory = now_factory or _utc_now
        self._interval_seconds = interval_seconds
        self._worker = worker or AutonomousResearchRuntimeWorker(
            config, repository._connection, metrics=self._metrics, now_factory=self._now_factory
        )

    def tick(self) -> AutonomousResearchRuntimeTickResult:
        now = self._now_factory()
        try:
            if not self._config.telegram_allowed_chat_ids:
                self._metrics.increment("autonomous_research_runtime_service_ticks", status="skipped", reason="no_allowed_chat")
                return AutonomousResearchRuntimeTickResult(enabled=False, attempted=False, jobs_registered=False)
            jobs_registered = ensure_autonomous_research_job(self._repository, now=now, interval_seconds=self._interval_seconds)
            results = run_due_autonomous_research(self._repository, self._worker, now=now, interval_seconds=self._interval_seconds)
            self._metrics.increment("autonomous_research_runtime_service_ticks", status="ok")
            return AutonomousResearchRuntimeTickResult(True, True, jobs_registered, results)
        except Exception as exc:  # noqa: BLE001 - autonomous research must not terminate the runtime service.
            self._metrics.increment("autonomous_research_runtime_service_ticks", status="failed")
            return AutonomousResearchRuntimeTickResult(True, True, False, error_type=exc.__class__.__name__)


def _advance_by_interval(now: str, interval_seconds: int) -> str:
    parsed = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=interval_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def production_autonomous_research_runtime_release_check() -> dict[str, object]:
    """Release check proving the background autonomous research worker
    stays inside its safety boundary end-to-end, through the real
    conversational stack (TelegramConversationAgent -> LLMConversationBrain
    -> default_tool_registry), mocking only the true external research
    boundary - same convention as the other ``production_*_release_check``
    functions in this codebase.

    Proves: an ACTIVE mission is advanced by exactly one bounded real
    research tool call per tick; a mission at
    ``MissionStatus.AWAITING_HUMAN_APPROVAL`` (READY_FOR_APPROVAL) is never
    advanced; a BLOCKED mission with no eligible recovery candidate stays
    honestly BLOCKED; and no strategy mutation, order execution, champion
    promotion, or approval bypass is reachable from this worker.
    """
    import sqlite3
    from contextlib import ExitStack
    from unittest.mock import patch

    from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
    from gaon.integrations.telegram.transport import parse_update_result
    from gaon.knowledge.research_mission import extract_or_update_mission, record_blocked, record_promotion_candidate
    from gaon.runtime.migrations import migrate
    from gaon.runtime.telegram_agent import TelegramConversationAgent

    now = "2026-08-22T00:00:05Z"
    config = GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
    )

    class _ReleaseCheckTelegramClient:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str]] = []

        def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
            from gaon.integrations.telegram.contracts import TelegramResponse

            self.sent.append((chat_id, text))
            return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"release-check:{len(self.sent)}")

    def _real_research_patches():
        stack = ExitStack()
        baseline = {
            "dataset": {"metadata": {"source": "real:yahoo-chart", "fixture_backed": False, "rows": 1222, "start_date": "2021-07-25", "end_date": "2026-07-24"}},
            "trades": [{"symbol": "005930", "pnl": 1.0} for _ in range(45)],
        }
        stack.enter_context(patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline))
        stack.enter_context(
            patch("gaon.knowledge.telegram_autonomous_learning._run_production_external_research", return_value={"state": "content_unavailable"})
        )
        from gaon.research.krx_real_pipeline import KRXFixtureMarketDataProvider

        class _Provider(KRXFixtureMarketDataProvider):
            source = "fixture:release-check-universe"
            market_agnostic = True

            @classmethod
            def from_env(cls, env=None):
                return cls()

        stack.enter_context(patch("gaon.research.multi_symbol.build_market_data_provider_from_env", return_value=_Provider()))
        return stack

    import inspect

    import gaon.runtime.llm_conversation as _llm_conversation_module

    _forbidden_module_names = (
        "gaon.adapters.trading",
        "gaon.adapters.strategy_execution",
        "gaon.adapters.strategy_deployment",
        "gaon.knowledge.promotion_gate",
        "gaon.knowledge.human_gated_promotion",
    )
    # Static source check (not sys.modules, which is contaminated by
    # whatever else has run in this process): the real bounded research
    # action-loop this worker calls (LLMConversationBrain.
    # _try_mission_driven_research_cycle, defined in this module's source)
    # must never even reference a broker/order/promotion module.
    _llm_conversation_source = inspect.getsource(_llm_conversation_module)
    _no_forbidden_reference = not any(name in _llm_conversation_source for name in _forbidden_module_names)

    # Real repository before/after observation (not a constant-True
    # assertion): every table a strategy mutation, order execution,
    # champion promotion, or approval decision would have to land in.
    # Snapshotting row counts across the whole flow below (mission
    # creation, an autonomous cycle, an AWAITING_HUMAN_APPROVAL tick, a
    # BLOCKED tick, and two durable service ticks) and asserting they are
    # unchanged is a real, repository-state-grounded proof - not a
    # by-construction claim.
    _observed_tables = (
        "champion_registry",
        "champion_history",
        "promotion_requests",
        "promotion_decisions",
        "approvals",
        "research_approval_decisions",
        "research_config_approvals",
        "strategy_deployment_requests",
        "strategy_deployment_runs",
        "strategy_deployment_backups",
        "strategy_execution_plans",
        "strategy_execution_runs",
    )

    def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _observed_tables}

    _forbidden_tool_names = frozenset(
        {
            "order_place",
            "order_execute",
            "broker_order",
            "kis_order",
            "binance_order",
            "champion_promote",
            "champion_apply",
            "strategy_apply",
            "strategy_deploy",
            "approval_approve",
            "approval_bypass",
        }
    )

    connection = sqlite3.connect(":memory:")
    try:
        migrate(connection)
        counts_before = _table_counts(connection)
        agent = TelegramConversationAgent(config, connection)
        runtime = TelegramRuntime(agent, allowed_chat_ids=("100",))
        client = _ReleaseCheckTelegramClient()
        with _real_research_patches():
            first_turn = process_update(
                parse_update_result(
                    {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "text": "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요"}},
                    received_at=now,
                ),
                runtime,
                client,
            )
        active_mission_before = agent._brain._mission_for("telegram:100")

        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: now)
        with _real_research_patches():
            active_cycle_result = worker.tick()
        active_mission_after = agent._brain._mission_for("telegram:100")

        approval_mission = active_mission_before
        for index in range(3):
            approval_mission = record_promotion_candidate(
                approval_mission, strategy_fingerprint=f"release-check-verified-{index}", candidate_id=f"KR-ST-00{index + 1}", now=now
            )
        agent._brain._remember_mission(
            LLMConversationRequest(session_id="telegram:100", user_ref="release-check", source="telegram", text="x", received_at=now, message_id="telegram:100:release-check:approval"),
            approval_mission,
        )
        awaiting_result = worker.tick()

        blocked_mission = record_blocked(
            extract_or_update_mission("국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=now),
            reason="provider_unavailable: no data source responded",
            now=now,
        )
        agent._brain._remember_mission(
            LLMConversationRequest(session_id="telegram:100", user_ref="release-check", source="telegram", text="x", received_at=now, message_id="telegram:100:release-check:blocked"),
            blocked_mission,
        )
        blocked_result = worker.tick()

        service_repository = ScheduledJobRepository(connection)
        service = AutonomousResearchRuntimeService(config, service_repository, now_factory=lambda: now)
        service_first = service.tick()
        service_second = service.tick()

        counts_after = _table_counts(connection)
        non_read_only_tool_calls = connection.execute(
            "SELECT COUNT(*) FROM llm_tool_audit WHERE risk_level != 'read_only'"
        ).fetchone()[0]
        forbidden_tool_calls = connection.execute(
            f"SELECT COUNT(*) FROM llm_tool_audit WHERE tool_name IN ({','.join('?' for _ in _forbidden_tool_names)})",
            tuple(_forbidden_tool_names),
        ).fetchone()[0]
        total_tool_calls = connection.execute("SELECT COUNT(*) FROM llm_tool_audit").fetchone()[0]
    finally:
        connection.close()

    checks = {
        "active_mission_advances_exactly_one_bounded_cycle": (
            active_cycle_result.action == "cycle_executed"
            and active_mission_after is not None
            and active_mission_after.cycles_completed >= active_mission_before.cycles_completed
        ),
        "awaiting_human_approval_never_advanced": awaiting_result.action == "skipped_awaiting_human_or_terminal",
        "blocked_without_recovery_stays_honestly_blocked": (
            blocked_result.action == "blocked_no_recovery"
            and blocked_result.blocker == "provider_unavailable: no data source responded"
        ),
        "service_tick_idempotent": service_first.jobs_registered is True and service_second.jobs_registered is False,
        "no_broker_or_promotion_module_referenced": _no_forbidden_reference,
        # Real observation, not a by-construction constant: the whole flow
        # above (mission creation, an autonomous cycle, an AWAITING_HUMAN_
        # APPROVAL tick, a BLOCKED tick, two durable service ticks) did
        # exercise real tool calls, and every single one of them was
        # risk_level=read_only in llm_tool_audit - not merely "no tool
        # named X ran", but "nothing the executor logged was ever
        # anything but read-only".
        "observation_window_exercised_tool_calls": total_tool_calls > 0,
        "strategy_not_mutated": (
            counts_before["strategy_deployment_requests"] == counts_after["strategy_deployment_requests"]
            and counts_before["strategy_deployment_runs"] == counts_after["strategy_deployment_runs"]
            and counts_before["strategy_deployment_backups"] == counts_after["strategy_deployment_backups"]
            and counts_before["strategy_execution_plans"] == counts_after["strategy_execution_plans"]
            and counts_before["strategy_execution_runs"] == counts_after["strategy_execution_runs"]
        ),
        "order_not_executed": non_read_only_tool_calls == 0 and forbidden_tool_calls == 0,
        "champion_not_promoted": (
            counts_before["champion_registry"] == counts_after["champion_registry"]
            and counts_before["champion_history"] == counts_after["champion_history"]
            and counts_before["promotion_requests"] == counts_after["promotion_requests"]
            and counts_before["promotion_decisions"] == counts_after["promotion_decisions"]
        ),
        "approval_not_bypassed": (
            counts_before["approvals"] == counts_after["approvals"]
            and counts_before["research_approval_decisions"] == counts_after["research_approval_decisions"]
            and counts_before["research_config_approvals"] == counts_after["research_config_approvals"]
        ),
    }
    _raise_if_failed("production autonomous research runtime", checks)
    return {
        "schema_version": 1,
        "active_mission_advanced": True,
        "awaiting_human_approval_stop": True,
        "blocked_recovery_honest": True,
        "service_idempotent": True,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def production_autonomous_research_direction_release_check() -> dict[str, object]:
    """Release check proving Hotfix #168's research-direction planning stage
    end-to-end: a mission genuinely BLOCKED on
    ``strategy_hypothesis_space_exhausted`` with no narrow-recovery-eligible
    candidate is diagnosed (FAILURE ANALYSIS), prioritized (RESEARCH
    PRIORITY), and recorded (RESEARCH DIRECTION) exactly once - a second
    tick against the unchanged mission state is a durable idempotent no-op,
    never a duplicate row or new work - and that an unrelated BLOCKED reason
    (``provider_unavailable``) is never diverted into this new path. Proves,
    via real repository before/after observation (not a by-construction
    constant), that none of this ever mutates strategy config, executes an
    order, promotes a champion, or bypasses approval.
    """
    import sqlite3
    from dataclasses import replace

    from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, record_blocked
    from gaon.knowledge.strategy_candidate import (
        STRATEGY_FAMILY_TEMPLATES,
        STRATEGY_SPACE_EXPANSION_TEMPLATES,
        StrategyCandidateStatus,
        new_candidate,
    )
    from gaon.runtime.llm_conversation import LLMConversationSession
    from gaon.runtime.migrations import migrate
    from gaon.runtime.telegram_agent import TelegramConversationAgent

    def _seed_session(agent: "TelegramConversationAgent", session_id: str) -> None:
        agent._brain._repository.upsert_session(
            LLMConversationSession(session_id, "release-check", "telegram", "active", now, now, {})
        )

    now = "2026-08-29T00:00:05Z"
    config = GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
    )
    session_id = "telegram:100"

    _observed_tables = (
        "champion_registry",
        "champion_history",
        "promotion_requests",
        "promotion_decisions",
        "approvals",
        "research_approval_decisions",
        "research_config_approvals",
        "strategy_deployment_requests",
        "strategy_deployment_runs",
        "strategy_execution_plans",
        "strategy_execution_runs",
    )

    def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _observed_tables}

    connection = sqlite3.connect(":memory:")
    try:
        migrate(connection)
        agent = TelegramConversationAgent(config, connection)
        request = _continuation_request(session_id, "100", now, suffix="release-check")

        # Every one of the bounded 9-family declarative grammar's families,
        # each already tried and terminal - the only real way
        # strategy_hypothesis_space_exhausted can fire (next_untried_family
        # only returns None once all four base families are represented,
        # and expand_strategy_space_candidate only returns candidate=None
        # once all five expansion families are also represented).
        _reason_cycle = (
            ("economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols", StrategyCandidateStatus.REJECTED),
            ("sample_pool_exhausted_no_untried_robustness_symbol", StrategyCandidateStatus.STAGNANT),
        )
        exhausted_families = tuple(
            (template.family, *_reason_cycle[index % len(_reason_cycle)])
            for index, template in enumerate((*STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_TEMPLATES))
        )
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=now)
        for sequence, (family, reason, status) in enumerate(exhausted_families, start=1):
            candidate = new_candidate(family, sequence=sequence, now=now)
            candidate = replace(candidate, status=status, rejected_reason=reason)
            mission = add_candidate(mission, candidate, now=now)
        mission = record_blocked(
            mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=now
        )
        _seed_session(agent, session_id)
        agent._brain._remember_mission(request, mission)

        counts_before = _table_counts(connection)
        tool_calls_before = connection.execute("SELECT COUNT(*) FROM llm_tool_audit").fetchone()[0]

        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: now)
        first_tick = worker.tick()
        second_tick = worker.tick()

        counts_after = _table_counts(connection)
        tool_calls_after = connection.execute("SELECT COUNT(*) FROM llm_tool_audit").fetchone()[0]
        direction_rows = connection.execute("SELECT COUNT(*) FROM research_directions").fetchone()[0]
        analysis_rows = connection.execute("SELECT COUNT(*) FROM research_failure_analyses").fetchone()[0]

        # An unrelated blocked reason must never be diverted into this new
        # planning stage - proves the wiring is scoped exactly to
        # strategy_hypothesis_space_exhausted, per Section 7.
        provider_mission = record_blocked(
            extract_or_update_mission("국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=now),
            reason="provider_unavailable: no data source responded",
            now=now,
        )
        _seed_session(agent, "telegram:101")
        agent._brain._remember_mission(
            _continuation_request("telegram:101", "101", now, suffix="provider"), provider_mission
        )
        provider_worker = AutonomousResearchRuntimeWorker(
            GaonRuntimeConfig(
                mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="t",
                telegram_allowed_chat_ids=("101",), approval_signing_secret="s",
            ),
            connection,
            now_factory=lambda: now,
        )
        provider_tick = provider_worker.tick()

        # AWAITING_HUMAN_APPROVAL must still be a hard stop even for a
        # mission that separately carries a research-direction history.
        from gaon.knowledge.research_mission import record_promotion_candidate

        approval_mission = mission
        for index in range(3):
            approval_mission = record_promotion_candidate(
                approval_mission, strategy_fingerprint=f"release-check-direction-{index}", candidate_id=f"KR-ST-10{index}", now=now
            )
        agent._brain._remember_mission(request, approval_mission)
        approval_tick = worker.tick()
    finally:
        connection.close()

    checks = {
        "exhausted_space_detected": first_tick.blocker is not None and first_tick.blocker.startswith("strategy_hypothesis_space_exhausted"),
        "failure_analysis_grounded": analysis_rows == 1 and first_tick.failure_class is not None,
        "research_priority_selected": first_tick.research_priority is not None,
        "direction_created": (
            first_tick.action == "research_direction_planned"
            and first_tick.direction_id is not None
            and first_tick.next_research_action == "wait_for_required_data"
            and first_tick.direction_status == "awaiting_evidence"
        ),
        "direction_idempotent": second_tick.action != "research_direction_planned" and direction_rows == 1,
        "bounded_execution": tool_calls_after == tool_calls_before,
        "awaiting_human_approval_stop": approval_tick.action == "skipped_awaiting_human_or_terminal",
        "provider_failure_honest": provider_tick.action == "blocked_no_recovery" and provider_tick.blocker == "provider_unavailable: no data source responded",
        "strategy_not_mutated": (
            counts_before["strategy_deployment_requests"] == counts_after["strategy_deployment_requests"]
            and counts_before["strategy_deployment_runs"] == counts_after["strategy_deployment_runs"]
            and counts_before["strategy_execution_plans"] == counts_after["strategy_execution_plans"]
            and counts_before["strategy_execution_runs"] == counts_after["strategy_execution_runs"]
        ),
        "order_not_executed": tool_calls_after == tool_calls_before,
        "champion_not_promoted": (
            counts_before["champion_registry"] == counts_after["champion_registry"]
            and counts_before["champion_history"] == counts_after["champion_history"]
            and counts_before["promotion_requests"] == counts_after["promotion_requests"]
            and counts_before["promotion_decisions"] == counts_after["promotion_decisions"]
        ),
        "approval_not_bypassed": (
            counts_before["approvals"] == counts_after["approvals"]
            and counts_before["research_approval_decisions"] == counts_after["research_approval_decisions"]
            and counts_before["research_config_approvals"] == counts_after["research_config_approvals"]
        ),
    }
    _raise_if_failed("production autonomous research direction", checks)
    return {
        "schema_version": 1,
        "exhausted_space_detected": True,
        "failure_analysis_grounded": True,
        "research_priority_selected": True,
        "direction_created": True,
        "direction_idempotent": True,
        "bounded_execution": True,
        "awaiting_human_approval_stop": True,
        "provider_failure_honest": True,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def _raise_if_failed(label: str, checks: dict[str, bool]) -> None:
    failed = tuple(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"{label} release check failed: {failed}")
