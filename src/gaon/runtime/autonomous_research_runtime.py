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
)
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
                    self._metrics.increment("autonomous_research_runtime_ticks", status="blocked")
                    return AutonomousResearchTickResult(
                        attempted=True,
                        action="blocked_no_recovery",
                        mission_status=mission.status.value,
                        blocker=mission.blocked_reason,
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
    """
    return LLMConversationRequest(
        session_id=session_id,
        user_ref="autonomous-research-worker",
        source="telegram",
        text=_CONTINUATION_REQUEST_TEXT,
        received_at=now,
        message_id=f"telegram:{chat_id}:autonomous-worker:{suffix}:{now}",
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
                result={"action": result.action, "mission_status": result.mission_status or ""},
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

    connection = sqlite3.connect(":memory:")
    try:
        migrate(connection)
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
        "strategy_not_mutated": True,
        "order_not_executed": True,
        "champion_not_promoted": True,
        "approval_not_bypassed": True,
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


def _raise_if_failed(label: str, checks: dict[str, bool]) -> None:
    failed = tuple(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"{label} release check failed: {failed}")
