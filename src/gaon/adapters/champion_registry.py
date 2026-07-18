"""Approval-gated Champion registry.

This module records Champion strategy state only. It does not connect to live
trading, broker credentials, or order execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import sqlite3
from typing import Any

from gaon.adapters.champion import ChampionChallengerDecision, ChampionChallengerEvaluationReport, SQLiteChampionChallengerRepository


DEFAULT_CHAMPION_SLOT = "default"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REF_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,127}$")


class PromotionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    ROLLED_BACK = "rolled_back"


class PromotionDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class ChampionRegistryEntry:
    slot: str
    active_version_id: str
    strategy_ref: str
    fingerprint: str
    source_backtest_id: str
    source_validation_id: str
    source_evaluation_id: str
    activated_at: str
    revision: int
    previous_version_id: str | None

    def __post_init__(self) -> None:
        _validate_ref(self.slot, "slot")
        _validate_ref(self.strategy_ref, "strategy_ref")
        _validate_ref(self.fingerprint, "fingerprint")
        _validate_utc(self.activated_at)
        if self.revision < 1:
            raise ValueError("champion revision must be positive")

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class ChampionStrategyVersion:
    version_id: str
    slot: str
    revision: int
    strategy_ref: str
    fingerprint: str
    source_backtest_id: str
    source_validation_id: str
    source_evaluation_id: str
    activated_at: str
    previous_version_id: str | None
    activation_type: str

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class PromotionRequest:
    promotion_id: str
    evaluation_id: str
    slot: str
    status: PromotionStatus
    champion_backtest_id: str
    challenger_backtest_id: str
    validation_id: str
    candidate_fingerprint: str
    current_champion_fingerprint: str
    requested_by: str
    requested_at: str

    def __post_init__(self) -> None:
        _validate_ref(self.promotion_id, "promotion_id")
        _validate_ref(self.slot, "slot")
        _validate_utc(self.requested_at)
        if not self.candidate_fingerprint or not self.current_champion_fingerprint:
            raise ValueError("promotion request requires fingerprints")

    def to_json(self) -> str:
        payload = self.__dict__ | {"status": self.status.value}
        return _dumps(payload)


@dataclass(frozen=True)
class PromotionDecisionRecord:
    decision_id: str
    promotion_id: str
    decision: PromotionDecision
    actor_ref: str
    decided_at: str
    reason: str

    def __post_init__(self) -> None:
        _validate_ref(self.decision_id, "decision_id")
        _validate_utc(self.decided_at)
        if not self.actor_ref:
            raise ValueError("promotion decision requires actor")

    def to_json(self) -> str:
        return _dumps(self.__dict__ | {"decision": self.decision.value})


@dataclass(frozen=True)
class ChampionActivationRecord:
    activation_id: str
    slot: str
    version_id: str
    promotion_id: str | None
    activated_by: str
    activated_at: str
    activation_type: str


@dataclass(frozen=True)
class ChampionRollbackRequest:
    rollback_id: str
    slot: str
    actor_ref: str
    requested_at: str


@dataclass(frozen=True)
class ChampionRollbackResult:
    rollback_id: str
    slot: str
    restored_version_id: str
    new_version_id: str
    status: PromotionStatus
    rolled_back_at: str


class SQLiteChampionRegistryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_active(self, slot: str = DEFAULT_CHAMPION_SLOT) -> ChampionRegistryEntry | None:
        row = self._connection.execute("SELECT payload_json FROM champion_registry WHERE slot = ?", (slot,)).fetchone()
        return _entry_from_json(str(row[0])) if row else None

    def put_active(self, entry: ChampionRegistryEntry) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET active_version_id = excluded.active_version_id, payload_json = excluded.payload_json, updated_at = excluded.updated_at",
                (entry.slot, entry.active_version_id, entry.to_json(), entry.activated_at),
            )

    def add_history(self, version: ChampionStrategyVersion) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO champion_history(version_id, slot, revision, strategy_ref, fingerprint, source_backtest_id, source_validation_id, source_evaluation_id, activated_at, previous_version_id, activation_type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (version.version_id, version.slot, version.revision, version.strategy_ref, version.fingerprint, version.source_backtest_id, version.source_validation_id, version.source_evaluation_id, version.activated_at, version.previous_version_id, version.activation_type, version.to_json()),
            )

    def list_history(self, slot: str = DEFAULT_CHAMPION_SLOT) -> tuple[ChampionStrategyVersion, ...]:
        rows = self._connection.execute("SELECT payload_json FROM champion_history WHERE slot = ? ORDER BY revision, activated_at, version_id", (slot,)).fetchall()
        return tuple(_version_from_json(str(row[0])) for row in rows)

    def get_request(self, promotion_id: str) -> PromotionRequest:
        row = self._connection.execute("SELECT payload_json FROM promotion_requests WHERE promotion_id = ?", (promotion_id,)).fetchone()
        if row is None:
            raise KeyError(promotion_id)
        return _request_from_json(str(row[0]))

    def find_request_by_evaluation(self, evaluation_id: str) -> PromotionRequest | None:
        row = self._connection.execute("SELECT payload_json FROM promotion_requests WHERE evaluation_id = ?", (evaluation_id,)).fetchone()
        return _request_from_json(str(row[0])) if row else None

    def add_request(self, request: PromotionRequest) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO promotion_requests(promotion_id, evaluation_id, status, slot, candidate_fingerprint, payload_json, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request.promotion_id, request.evaluation_id, request.status.value, request.slot, request.candidate_fingerprint, request.to_json(), request.requested_at),
            )

    def update_request(self, request: PromotionRequest) -> None:
        with self._connection:
            updated = self._connection.execute(
                "UPDATE promotion_requests SET status = ?, payload_json = ? WHERE promotion_id = ?",
                (request.status.value, request.to_json(), request.promotion_id),
            ).rowcount
            if updated != 1:
                raise KeyError(request.promotion_id)

    def add_decision(self, decision: PromotionDecisionRecord) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO promotion_decisions(decision_id, promotion_id, decision, actor_ref, decided_at, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (decision.decision_id, decision.promotion_id, decision.decision.value, decision.actor_ref, decision.decided_at, decision.to_json()),
            )


class ChampionRegistryService:
    def __init__(
        self,
        repository: SQLiteChampionRegistryRepository,
        evaluations: SQLiteChampionChallengerRepository,
        *,
        event_store: Any | None = None,
        metrics: Any | None = None,
    ) -> None:
        self._repository = repository
        self._evaluations = evaluations
        self._event_store = event_store
        self._metrics = metrics

    def bootstrap(self, *, strategy_ref: str, fingerprint: str, backtest_id: str, actor_ref: str, activated_at: str, slot: str = DEFAULT_CHAMPION_SLOT) -> ChampionRegistryEntry:
        if self._repository.get_active(slot) is not None:
            raise ValueError("champion slot already has an active champion")
        entry = self._activate(
            slot=slot,
            strategy_ref=strategy_ref,
            fingerprint=fingerprint,
            backtest_id=backtest_id,
            validation_id="bootstrap",
            evaluation_id="bootstrap",
            actor_ref=actor_ref,
            activated_at=activated_at,
            previous=None,
            activation_type="bootstrap",
            promotion_id=None,
        )
        self._record("ChampionBootstrapCreated", entry.active_version_id, actor_ref, activated_at, {"slot": slot, "fingerprint": fingerprint})
        return entry

    def request_promotion(self, promotion_id: str, evaluation_id: str, *, actor_ref: str, requested_at: str, slot: str = DEFAULT_CHAMPION_SLOT) -> PromotionRequest:
        existing = self._repository.find_request_by_evaluation(evaluation_id)
        if existing is not None:
            if existing.promotion_id != promotion_id:
                raise ValueError("promotion request already exists for evaluation")
            return existing
        report = self._evaluations.get_report(evaluation_id)
        current = self._repository.get_active(slot)
        _validate_promotion_candidate(report, current)
        request = PromotionRequest(
            promotion_id,
            evaluation_id,
            slot,
            PromotionStatus.PENDING_APPROVAL,
            report.champion_backtest_id,
            report.challenger_backtest_id,
            report.validation_id,
            report.challenger_fingerprint,
            report.champion_fingerprint,
            actor_ref,
            requested_at,
        )
        self._repository.add_request(request)
        self._record("ChampionPromotionRequested", promotion_id, actor_ref, requested_at, {"evaluation_id": evaluation_id, "slot": slot})
        _increment(self._metrics, "gaon_champion_promotion_requests_total")
        return request

    def approve(self, promotion_id: str, *, actor_ref: str, decided_at: str, reason: str = "explicit approval") -> ChampionRegistryEntry:
        request = self._repository.get_request(promotion_id)
        if request.status == PromotionStatus.ACTIVATED:
            active = self._repository.get_active(request.slot)
            if active is None:
                raise ValueError("activated request has no active champion")
            return active
        if request.status == PromotionStatus.REJECTED:
            raise ValueError("rejected promotion cannot be approved")
        if request.status not in {PromotionStatus.PENDING_APPROVAL, PromotionStatus.APPROVED}:
            raise ValueError("promotion request cannot be approved from current state")
        report = self._evaluations.get_report(request.evaluation_id)
        current = self._repository.get_active(request.slot)
        _validate_promotion_candidate(report, current)
        decision = PromotionDecisionRecord(f"decision:{promotion_id}:approve", promotion_id, PromotionDecision.APPROVE, actor_ref, decided_at, reason)
        self._repository.add_decision(decision)
        self._record("ChampionPromotionApproved", promotion_id, actor_ref, decided_at, {"promotion_id": promotion_id})
        _increment(self._metrics, "gaon_champion_promotions_approved_total")
        entry = self._activate(
            slot=request.slot,
            strategy_ref=_strategy_ref_from_backtest_id(report.challenger_backtest_id),
            fingerprint=report.challenger_fingerprint,
            backtest_id=report.challenger_backtest_id,
            validation_id=report.validation_id,
            evaluation_id=report.evaluation_id,
            actor_ref=actor_ref,
            activated_at=decided_at,
            previous=current,
            activation_type="promotion",
            promotion_id=promotion_id,
        )
        self._repository.update_request(_replace_request_status(request, PromotionStatus.ACTIVATED))
        self._record("ChampionActivated", entry.active_version_id, actor_ref, decided_at, {"promotion_id": promotion_id, "slot": request.slot})
        _increment(self._metrics, "gaon_champion_activations_total")
        return entry

    def reject(self, promotion_id: str, *, actor_ref: str, decided_at: str, reason: str = "explicit rejection") -> PromotionRequest:
        request = self._repository.get_request(promotion_id)
        if request.status == PromotionStatus.REJECTED:
            return request
        if request.status == PromotionStatus.ACTIVATED:
            raise ValueError("activated promotion cannot be rejected")
        decision = PromotionDecisionRecord(f"decision:{promotion_id}:reject", promotion_id, PromotionDecision.REJECT, actor_ref, decided_at, reason)
        self._repository.add_decision(decision)
        rejected = _replace_request_status(request, PromotionStatus.REJECTED)
        self._repository.update_request(rejected)
        self._record("ChampionPromotionRejected", promotion_id, actor_ref, decided_at, {"promotion_id": promotion_id})
        _increment(self._metrics, "gaon_champion_promotions_rejected_total")
        return rejected

    def rollback(self, request: ChampionRollbackRequest) -> ChampionRollbackResult:
        active = self._repository.get_active(request.slot)
        if active is None or active.previous_version_id is None:
            raise ValueError("no previous champion exists for rollback")
        previous = _find_version(self._repository.list_history(request.slot), active.previous_version_id)
        self._record("ChampionRollbackRequested", request.rollback_id, request.actor_ref, request.requested_at, {"slot": request.slot})
        entry = self._activate(
            slot=request.slot,
            strategy_ref=previous.strategy_ref,
            fingerprint=previous.fingerprint,
            backtest_id=previous.source_backtest_id,
            validation_id=previous.source_validation_id,
            evaluation_id=previous.source_evaluation_id,
            actor_ref=request.actor_ref,
            activated_at=request.requested_at,
            previous=active,
            activation_type="rollback",
            promotion_id=None,
        )
        result = ChampionRollbackResult(request.rollback_id, request.slot, previous.version_id, entry.active_version_id, PromotionStatus.ROLLED_BACK, request.requested_at)
        self._record("ChampionRolledBack", request.rollback_id, request.actor_ref, request.requested_at, {"restored_version_id": previous.version_id, "new_version_id": entry.active_version_id})
        _increment(self._metrics, "gaon_champion_rollbacks_total")
        return result

    def _activate(
        self,
        *,
        slot: str,
        strategy_ref: str,
        fingerprint: str,
        backtest_id: str,
        validation_id: str,
        evaluation_id: str,
        actor_ref: str,
        activated_at: str,
        previous: ChampionRegistryEntry | None,
        activation_type: str,
        promotion_id: str | None,
    ) -> ChampionRegistryEntry:
        revision = 1 if previous is None else previous.revision + 1
        version_id = f"champion-version:{slot}:{revision}"
        version = ChampionStrategyVersion(version_id, slot, revision, strategy_ref, fingerprint, backtest_id, validation_id, evaluation_id, activated_at, previous.active_version_id if previous else None, activation_type)
        entry = ChampionRegistryEntry(slot, version_id, strategy_ref, fingerprint, backtest_id, validation_id, evaluation_id, activated_at, revision, version.previous_version_id)
        self._repository.add_history(version)
        self._repository.put_active(entry)
        return entry

    def _record(self, event_type: str, correlation_id: str, actor_ref: str, at: str, payload: dict[str, object]) -> None:
        if self._event_store is not None:
            from gaon.runtime.event_store import DurableEvent

            try:
                self._event_store.append(
                    DurableEvent(
                        event_id=f"event:champion-registry:{event_type}:{correlation_id}",
                        event_type=event_type,
                        occurred_at=at,
                        actor_ref=actor_ref,
                        correlation_id=correlation_id,
                        causation_id=None,
                        scope="champion_registry",
                        project="StrategyLab",
                        strategy=str(payload.get("slot", DEFAULT_CHAMPION_SLOT)),
                        market="N/A",
                        payload=payload,
                        evidence_refs=tuple(str(value) for key, value in payload.items() if key.endswith("_id")),
                        audit_refs=(),
                        appended_at=at,
                    )
                )
            except sqlite3.IntegrityError:
                return


def _validate_promotion_candidate(report: ChampionChallengerEvaluationReport, current: ChampionRegistryEntry | None) -> None:
    if report.decision is not ChampionChallengerDecision.PROMOTION_CANDIDATE:
        raise ValueError("only promotion_candidate evaluations can create promotion requests")
    if not report.challenger_fingerprint or not report.champion_fingerprint:
        raise ValueError("promotion candidate requires fingerprints")
    if report.challenger_fingerprint == report.champion_fingerprint:
        raise ValueError("candidate fingerprint must differ from champion")
    if current is not None and current.fingerprint == report.challenger_fingerprint:
        raise ValueError("candidate is already the active champion")


def _replace_request_status(request: PromotionRequest, status: PromotionStatus) -> PromotionRequest:
    return PromotionRequest(request.promotion_id, request.evaluation_id, request.slot, status, request.champion_backtest_id, request.challenger_backtest_id, request.validation_id, request.candidate_fingerprint, request.current_champion_fingerprint, request.requested_by, request.requested_at)


def _entry_from_json(value: str) -> ChampionRegistryEntry:
    return ChampionRegistryEntry(**json.loads(value))


def _version_from_json(value: str) -> ChampionStrategyVersion:
    return ChampionStrategyVersion(**json.loads(value))


def _request_from_json(value: str) -> PromotionRequest:
    payload = json.loads(value)
    payload["status"] = PromotionStatus(str(payload["status"]))
    return PromotionRequest(**payload)


def _find_version(versions: tuple[ChampionStrategyVersion, ...], version_id: str) -> ChampionStrategyVersion:
    for version in versions:
        if version.version_id == version_id:
            return version
    raise KeyError(version_id)


def _strategy_ref_from_backtest_id(backtest_id: str) -> str:
    return "strategy:" + backtest_id.rsplit(":", 1)[-1][:24]


def _validate_ref(value: str, label: str) -> None:
    if REF_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="champion_registry")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
