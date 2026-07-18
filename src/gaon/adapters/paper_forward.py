"""Paper-only Champion forward-test sessions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import sqlite3
from typing import Any

from gaon.adapters.champion_registry import DEFAULT_CHAMPION_SLOT, ChampionRegistryEntry, SQLiteChampionRegistryRepository
from gaon.adapters.trading import PaperTradingAdapter, SQLiteTradingRepository, TradingExecutionService, TradingIntent, TradingResult, TradingRiskPolicy, TradingStatus, build_trading_request


PAPER_FORWARD_TEST_POLICY_VERSION = "paper_forward_test_policy_v1"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REF_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,127}$")


class PaperTradingSessionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PaperForwardTestPolicy:
    policy_version: str = PAPER_FORWARD_TEST_POLICY_VERSION
    minimum_session_days_placeholder: int = 20
    minimum_simulated_trades: int = 10
    maximum_allowed_paper_drawdown: float | None = None


@dataclass(frozen=True)
class PaperTradingPromotionRequest:
    request_id: str
    slot: str
    champion_version_id: str
    strategy_ref: str
    fingerprint: str
    requested_by: str
    requested_at: str
    policy_version: str = PAPER_FORWARD_TEST_POLICY_VERSION

    def __post_init__(self) -> None:
        _validate_ref(self.request_id, "request_id")
        _validate_utc(self.requested_at)

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class PaperTradingSession:
    session_id: str
    slot: str
    champion_version_id: str
    strategy_ref: str
    fingerprint: str
    status: PaperTradingSessionStatus
    policy_version: str
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_ref(self.session_id, "session_id")
        _validate_utc(self.created_at)
        if self.started_at is not None:
            _validate_utc(self.started_at)
        if self.ended_at is not None:
            _validate_utc(self.ended_at)

    def to_json(self) -> str:
        return _dumps(
            {
                "session_id": self.session_id,
                "slot": self.slot,
                "champion_version_id": self.champion_version_id,
                "strategy_ref": self.strategy_ref,
                "fingerprint": self.fingerprint,
                "status": self.status.value,
                "policy_version": self.policy_version,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
            }
        )


@dataclass(frozen=True)
class PaperTradingObservation:
    observation_id: str
    session_id: str
    observed_at: str
    trading_result_id: str | None
    status: str
    notional: float
    message: str

    def __post_init__(self) -> None:
        _validate_ref(self.observation_id, "observation_id")
        _validate_utc(self.observed_at)

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class PaperTradingPerformanceSummary:
    session_id: str
    status: PaperTradingSessionStatus
    champion_version_id: str
    strategy_ref: str
    fingerprint: str
    simulated_orders: int
    fills: int
    rejected_simulated_orders: int
    failed_simulated_orders: int
    realized_paper_pnl: float | None
    unrealized_paper_pnl: float | None
    max_paper_drawdown: float | None
    exposure: float | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    generated_at: str

    def to_json(self) -> str:
        return _dumps(
            {
                "session_id": self.session_id,
                "status": self.status.value,
                "champion_version_id": self.champion_version_id,
                "strategy_ref": self.strategy_ref,
                "fingerprint": self.fingerprint,
                "simulated_orders": self.simulated_orders,
                "fills": self.fills,
                "rejected_simulated_orders": self.rejected_simulated_orders,
                "failed_simulated_orders": self.failed_simulated_orders,
                "realized_paper_pnl": self.realized_paper_pnl,
                "unrealized_paper_pnl": self.unrealized_paper_pnl,
                "max_paper_drawdown": self.max_paper_drawdown,
                "exposure": self.exposure,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
                "generated_at": self.generated_at,
            }
        )


class SQLitePaperTradingSessionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_session(self, session: PaperTradingSession) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO paper_trading_sessions(session_id, slot, champion_version_id, status, fingerprint, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session.session_id, session.slot, session.champion_version_id, session.status.value, session.fingerprint, session.to_json(), session.created_at, session.created_at),
            )

    def update_session(self, session: PaperTradingSession, updated_at: str) -> None:
        with self._connection:
            updated = self._connection.execute(
                "UPDATE paper_trading_sessions SET status = ?, payload_json = ?, updated_at = ? WHERE session_id = ?",
                (session.status.value, session.to_json(), updated_at, session.session_id),
            ).rowcount
            if updated != 1:
                raise KeyError(session.session_id)

    def get_session(self, session_id: str) -> PaperTradingSession:
        row = self._connection.execute("SELECT payload_json FROM paper_trading_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _session_from_json(str(row[0]))

    def list_sessions(self) -> tuple[PaperTradingSession, ...]:
        rows = self._connection.execute("SELECT payload_json FROM paper_trading_sessions ORDER BY created_at, session_id").fetchall()
        return tuple(_session_from_json(str(row[0])) for row in rows)

    def add_observation(self, observation: PaperTradingObservation) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO paper_trading_observations(observation_id, session_id, observed_at, status, payload_json) VALUES (?, ?, ?, ?, ?)",
                (observation.observation_id, observation.session_id, observation.observed_at, observation.status, observation.to_json()),
            )

    def list_observations(self, session_id: str) -> tuple[PaperTradingObservation, ...]:
        rows = self._connection.execute("SELECT payload_json FROM paper_trading_observations WHERE session_id = ? ORDER BY observed_at, observation_id", (session_id,)).fetchall()
        return tuple(_observation_from_json(str(row[0])) for row in rows)

    def put_summary(self, summary: PaperTradingPerformanceSummary) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO paper_trading_summaries(session_id, status, payload_json, generated_at) VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET status = excluded.status, payload_json = excluded.payload_json, generated_at = excluded.generated_at",
                (summary.session_id, summary.status.value, summary.to_json(), summary.generated_at),
            )

    def get_summary(self, session_id: str) -> PaperTradingPerformanceSummary:
        row = self._connection.execute("SELECT payload_json FROM paper_trading_summaries WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _summary_from_json(str(row[0]))


class PaperTradingForwardTestService:
    def __init__(
        self,
        sessions: SQLitePaperTradingSessionRepository,
        registry: SQLiteChampionRegistryRepository,
        *,
        trading_repository: SQLiteTradingRepository | None = None,
        event_store: Any | None = None,
        metrics: Any | None = None,
        adapter: PaperTradingAdapter | None = None,
    ) -> None:
        self._sessions = sessions
        self._registry = registry
        self._trading_repository = trading_repository
        self._event_store = event_store
        self._metrics = metrics
        self._adapter = adapter or PaperTradingAdapter()

    def create_session(self, session_id: str, *, slot: str = DEFAULT_CHAMPION_SLOT, champion_version_id: str | None = None, fingerprint: str | None = None, actor_ref: str, created_at: str) -> PaperTradingSession:
        active = self._active(slot)
        if champion_version_id is not None and champion_version_id != active.active_version_id:
            raise ValueError("only the active champion version can start paper forward test")
        if fingerprint is not None and fingerprint != active.fingerprint:
            raise ValueError("champion fingerprint mismatch")
        session = PaperTradingSession(session_id, slot, active.active_version_id, active.strategy_ref, active.fingerprint, PaperTradingSessionStatus.PENDING, PAPER_FORWARD_TEST_POLICY_VERSION, created_at)
        self._sessions.add_session(session)
        self._record("PaperTradingPromotionRequested", session, actor_ref, created_at)
        self._record("PaperTradingSessionCreated", session, actor_ref, created_at)
        _increment(self._metrics, "gaon_paper_sessions_total")
        return session

    def start(self, session_id: str, *, actor_ref: str, at: str) -> PaperTradingSession:
        session = self._sessions.get_session(session_id)
        if session.status == PaperTradingSessionStatus.ACTIVE:
            return session
        _require_status(session, {PaperTradingSessionStatus.PENDING})
        active = self._active(session.slot)
        _require_same_champion(session, active)
        updated = _replace_session(session, status=PaperTradingSessionStatus.ACTIVE, started_at=at)
        self._sessions.update_session(updated, at)
        self._record("PaperTradingSessionStarted", updated, actor_ref, at)
        _gauge(self._metrics, "gaon_paper_sessions_active", 1)
        return updated

    def pause(self, session_id: str, *, actor_ref: str, at: str) -> PaperTradingSession:
        session = self._sessions.get_session(session_id)
        _require_status(session, {PaperTradingSessionStatus.ACTIVE})
        updated = _replace_session(session, status=PaperTradingSessionStatus.PAUSED)
        self._sessions.update_session(updated, at)
        self._record("PaperTradingSessionPaused", updated, actor_ref, at)
        _gauge(self._metrics, "gaon_paper_sessions_active", 0)
        return updated

    def resume(self, session_id: str, *, actor_ref: str, at: str) -> PaperTradingSession:
        session = self._sessions.get_session(session_id)
        _require_status(session, {PaperTradingSessionStatus.PAUSED})
        active = self._active(session.slot)
        _require_same_champion(session, active)
        updated = _replace_session(session, status=PaperTradingSessionStatus.ACTIVE)
        self._sessions.update_session(updated, at)
        self._record("PaperTradingSessionResumed", updated, actor_ref, at)
        _gauge(self._metrics, "gaon_paper_sessions_active", 1)
        return updated

    def complete(self, session_id: str, *, actor_ref: str, at: str) -> PaperTradingSession:
        session = self._sessions.get_session(session_id)
        _require_status(session, {PaperTradingSessionStatus.ACTIVE, PaperTradingSessionStatus.PAUSED})
        updated = _replace_session(session, status=PaperTradingSessionStatus.COMPLETED, ended_at=at)
        self._sessions.update_session(updated, at)
        self._record("PaperTradingSessionCompleted", updated, actor_ref, at)
        _increment(self._metrics, "gaon_paper_sessions_completed_total")
        _gauge(self._metrics, "gaon_paper_sessions_active", 0)
        self.summary(session_id, generated_at=at)
        return updated

    def cancel(self, session_id: str, *, actor_ref: str, at: str) -> PaperTradingSession:
        session = self._sessions.get_session(session_id)
        _require_status(session, {PaperTradingSessionStatus.PENDING, PaperTradingSessionStatus.ACTIVE, PaperTradingSessionStatus.PAUSED})
        updated = _replace_session(session, status=PaperTradingSessionStatus.CANCELLED, ended_at=at)
        self._sessions.update_session(updated, at)
        self._record("PaperTradingSessionCancelled", updated, actor_ref, at)
        _gauge(self._metrics, "gaon_paper_sessions_active", 0)
        return updated

    def simulate_order(self, session_id: str, *, symbol: str, quantity: float, price: float, side: str, actor_ref: str, at: str) -> TradingResult:
        session = self._sessions.get_session(session_id)
        _require_status(session, {PaperTradingSessionStatus.ACTIVE})
        active = self._active(session.slot)
        _require_same_champion(session, active)
        intent = TradingIntent.SIMULATE_SELL if side == "sell" else TradingIntent.SIMULATE_BUY
        request = build_trading_request(f"paper-session:{session_id}:{len(self._sessions.list_observations(session_id)) + 1}", intent, symbol=symbol, quantity=quantity, price=price, actor_ref=actor_ref, created_at=at, idempotency_key=f"paper-session:{session_id}:{symbol}:{side}:{at}")
        result = TradingExecutionService(self._adapter, TradingRiskPolicy(), repository=self._trading_repository, event_store=self._event_store, metrics=self._metrics).execute(request)
        observation = PaperTradingObservation(f"paper-observation:{session_id}:{len(self._sessions.list_observations(session_id)) + 1}", session_id, at, result.result_id, result.status.value, result.notional, result.message)
        self._sessions.add_observation(observation)
        if result.status == TradingStatus.SIMULATED:
            _increment(self._metrics, "gaon_paper_simulated_orders_total")
        return result

    def summary(self, session_id: str, *, generated_at: str) -> PaperTradingPerformanceSummary:
        session = self._sessions.get_session(session_id)
        observations = self._sessions.list_observations(session_id)
        fills = sum(1 for item in observations if item.status == TradingStatus.SIMULATED.value)
        rejected = sum(1 for item in observations if item.status in {TradingStatus.REJECTED.value, TradingStatus.BLOCKED.value})
        failed = sum(1 for item in observations if item.status == TradingStatus.FAILED.value)
        summary = PaperTradingPerformanceSummary(session.session_id, session.status, session.champion_version_id, session.strategy_ref, session.fingerprint, len(observations), fills, rejected, failed, None, None, None, None, session.warnings, session.errors, generated_at)
        self._sessions.put_summary(summary)
        return summary

    def _active(self, slot: str) -> ChampionRegistryEntry:
        active = self._registry.get_active(slot)
        if active is None:
            raise ValueError("active champion is required for paper forward test")
        return active

    def _record(self, event_type: str, session: PaperTradingSession, actor_ref: str, at: str) -> None:
        if self._event_store is not None:
            from gaon.runtime.event_store import DurableEvent

            try:
                self._event_store.append(
                    DurableEvent(
                        event_id=f"event:paper-forward:{event_type}:{session.session_id}:{at}",
                        event_type=event_type,
                        occurred_at=at,
                        actor_ref=actor_ref,
                        correlation_id=session.session_id,
                        causation_id=session.champion_version_id,
                        scope="paper_forward_test",
                        project="StrategyLab",
                        strategy=session.strategy_ref,
                        market="N/A",
                        payload={"session_id": session.session_id, "status": session.status.value, "champion_version_id": session.champion_version_id, "fingerprint": session.fingerprint},
                        evidence_refs=(session.champion_version_id,),
                        audit_refs=(),
                        appended_at=at,
                    )
                )
            except sqlite3.IntegrityError:
                return


def _replace_session(session: PaperTradingSession, *, status: PaperTradingSessionStatus, started_at: str | None = None, ended_at: str | None = None) -> PaperTradingSession:
    return PaperTradingSession(session.session_id, session.slot, session.champion_version_id, session.strategy_ref, session.fingerprint, status, session.policy_version, session.created_at, started_at if started_at is not None else session.started_at, ended_at if ended_at is not None else session.ended_at, session.warnings, session.errors)


def _require_status(session: PaperTradingSession, allowed: set[PaperTradingSessionStatus]) -> None:
    if session.status not in allowed:
        raise ValueError(f"invalid paper session transition from {session.status.value}")


def _require_same_champion(session: PaperTradingSession, active: ChampionRegistryEntry) -> None:
    if session.champion_version_id != active.active_version_id or session.fingerprint != active.fingerprint:
        raise ValueError("paper session champion is no longer active")


def _session_from_json(value: str) -> PaperTradingSession:
    payload = json.loads(value)
    payload["status"] = PaperTradingSessionStatus(str(payload["status"]))
    payload["warnings"] = tuple(str(item) for item in payload["warnings"])
    payload["errors"] = tuple(str(item) for item in payload["errors"])
    return PaperTradingSession(**payload)


def _observation_from_json(value: str) -> PaperTradingObservation:
    return PaperTradingObservation(**json.loads(value))


def _summary_from_json(value: str) -> PaperTradingPerformanceSummary:
    payload = json.loads(value)
    payload["status"] = PaperTradingSessionStatus(str(payload["status"]))
    payload["warnings"] = tuple(str(item) for item in payload["warnings"])
    payload["errors"] = tuple(str(item) for item in payload["errors"])
    return PaperTradingPerformanceSummary(**payload)


def _validate_ref(value: str, label: str) -> None:
    if REF_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="paper_forward")


def _gauge(metrics: Any | None, name: str, value: float) -> None:
    if metrics is not None:
        metrics.gauge(name, value, component="paper_forward")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
