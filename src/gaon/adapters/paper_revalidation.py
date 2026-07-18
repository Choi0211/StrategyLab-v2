"""Paper forward-test revalidation and safety gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import sqlite3
from typing import Any

from gaon.adapters.champion_registry import ChampionRegistryEntry
from gaon.adapters.paper_forward import PaperTradingPerformanceSummary, PaperTradingSession, PaperTradingSessionStatus


PAPER_REVALIDATION_POLICY_VERSION = "paper_revalidation_policy_v1"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class PaperRevalidationStatus(str, Enum):
    LIVE_ELIGIBLE = "live_eligible"
    HOLD = "hold"
    KILL = "kill"
    ROLLBACK_RECOMMENDED = "rollback_recommended"
    REVIEW = "review"


class RiskGateDecision(str, Enum):
    PASS = "pass"
    HOLD = "hold"
    KILL = "kill"
    ROLLBACK_RECOMMENDED = "rollback_recommended"
    REVIEW = "review"


class KillGateReason(str, Enum):
    CRITICAL_EXECUTION_ERROR = "critical_execution_error"
    CORRUPTED_SESSION_STATE = "corrupted_session_state"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    IMPOSSIBLE_METRIC = "impossible_metric"
    EXTREME_PAPER_DRAWDOWN = "extreme_paper_drawdown"


@dataclass(frozen=True)
class RollbackRecommendation:
    recommended: bool
    reason: str
    previous_champion_ref: str | None = None


@dataclass(frozen=True)
class PaperRevalidationPolicy:
    policy_version: str = PAPER_REVALIDATION_POLICY_VERSION
    minimum_simulated_trades: int = 20
    maximum_paper_drawdown: float = 0.20
    hard_kill_paper_drawdown: float = 0.35
    maximum_rejection_rate: float = 0.25


@dataclass(frozen=True)
class PaperRevalidationRequest:
    revalidation_id: str
    session_id: str
    champion_version_id: str
    policy_version: str
    requested_at: str
    actor_ref: str

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class PaperRevalidationRuleResult:
    rule: str
    decision: RiskGateDecision
    observed: str
    threshold: str
    message: str


@dataclass(frozen=True)
class PaperRevalidationReport:
    revalidation_id: str
    status: PaperRevalidationStatus
    policy_version: str
    session_id: str
    champion_version_id: str
    fingerprint: str
    rule_results: tuple[PaperRevalidationRuleResult, ...]
    warnings: tuple[str, ...]
    kill_reasons: tuple[KillGateReason, ...]
    rollback: RollbackRecommendation
    generated_at: str

    def to_json(self) -> str:
        return _dumps(
            {
                "revalidation_id": self.revalidation_id,
                "status": self.status.value,
                "policy_version": self.policy_version,
                "session_id": self.session_id,
                "champion_version_id": self.champion_version_id,
                "fingerprint": self.fingerprint,
                "rule_results": [rule.__dict__ | {"decision": rule.decision.value} for rule in self.rule_results],
                "warnings": list(self.warnings),
                "kill_reasons": [reason.value for reason in self.kill_reasons],
                "rollback": self.rollback.__dict__,
                "generated_at": self.generated_at,
            }
        )


class SQLitePaperRevalidationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: PaperRevalidationRequest) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO paper_revalidation_requests(revalidation_id, session_id, champion_version_id, policy_version, payload_json, requested_at) VALUES (?, ?, ?, ?, ?, ?)",
                (request.revalidation_id, request.session_id, request.champion_version_id, request.policy_version, request.to_json(), request.requested_at),
            )

    def add_report(self, report: PaperRevalidationReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO paper_revalidation_reports(revalidation_id, status, policy_version, session_id, champion_version_id, payload_json, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report.revalidation_id, report.status.value, report.policy_version, report.session_id, report.champion_version_id, report.to_json(), report.generated_at),
            )

    def get_report(self, revalidation_id: str) -> PaperRevalidationReport:
        row = self._connection.execute("SELECT payload_json FROM paper_revalidation_reports WHERE revalidation_id = ?", (revalidation_id,)).fetchone()
        if row is None:
            raise KeyError(revalidation_id)
        return report_from_json(str(row[0]))

    def list_reports(self) -> tuple[PaperRevalidationReport, ...]:
        rows = self._connection.execute("SELECT payload_json FROM paper_revalidation_reports ORDER BY generated_at, revalidation_id").fetchall()
        return tuple(report_from_json(str(row[0])) for row in rows)


class PaperRevalidationEngine:
    def __init__(self, policy: PaperRevalidationPolicy | None = None, *, repository: SQLitePaperRevalidationRepository | None = None, event_store: Any | None = None, metrics: Any | None = None) -> None:
        self._policy = policy or PaperRevalidationPolicy()
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics

    @property
    def policy(self) -> PaperRevalidationPolicy:
        return self._policy

    def revalidate(self, request: PaperRevalidationRequest, *, active: ChampionRegistryEntry, session: PaperTradingSession, summary: PaperTradingPerformanceSummary, generated_at: str) -> PaperRevalidationReport:
        _validate_utc(generated_at)
        if self._repository is not None:
            self._repository.add_request(request)
        self._record("PaperRevalidationRequested", request, None, generated_at)
        self._record("PaperRevalidationStarted", request, None, generated_at)
        _increment(self._metrics, "gaon_paper_revalidations_total")
        rules = (
            _session_state_rule(session, summary),
            _fingerprint_rule(active, session, summary),
            _trade_count_rule(summary, self._policy),
            _execution_error_rule(summary),
            _drawdown_rule(summary, self._policy),
            _rejection_rate_rule(summary, self._policy),
            _missing_metric_rule(summary),
        )
        status = _status(rules)
        kill_reasons = _kill_reasons(rules)
        rollback = RollbackRecommendation(status == PaperRevalidationStatus.ROLLBACK_RECOMMENDED, "paper risk deterioration recommends human-reviewed rollback" if status == PaperRevalidationStatus.ROLLBACK_RECOMMENDED else "not recommended", active.previous_version_id)
        warnings = tuple(rule.message for rule in rules if rule.decision in {RiskGateDecision.HOLD, RiskGateDecision.REVIEW, RiskGateDecision.ROLLBACK_RECOMMENDED})
        report = PaperRevalidationReport(request.revalidation_id, status, self._policy.policy_version, session.session_id, session.champion_version_id, session.fingerprint, rules, warnings, kill_reasons, rollback, generated_at)
        if self._repository is not None:
            self._repository.add_report(report)
        self._record("PaperRevalidationCompleted", request, report, generated_at)
        self._record(_event_for_status(status), request, report, generated_at)
        _increment(self._metrics, _metric_for_status(status))
        return report

    def _record(self, event_type: str, request: PaperRevalidationRequest, report: PaperRevalidationReport | None, at: str) -> None:
        if self._event_store is not None:
            from gaon.runtime.event_store import DurableEvent

            try:
                self._event_store.append(
                    DurableEvent(
                        event_id=f"event:paper-revalidation:{event_type}:{request.revalidation_id}",
                        event_type=event_type,
                        occurred_at=at,
                        actor_ref=request.actor_ref,
                        correlation_id=request.revalidation_id,
                        causation_id=request.session_id,
                        scope="paper_revalidation",
                        project="StrategyLab",
                        strategy="N/A",
                        market="N/A",
                        payload={"revalidation_id": request.revalidation_id, "session_id": request.session_id, "status": report.status.value if report else "requested"},
                        evidence_refs=(request.session_id, request.champion_version_id),
                        audit_refs=(),
                        appended_at=at,
                    )
                )
            except sqlite3.IntegrityError:
                return


def build_paper_revalidation_request(revalidation_id: str, *, session: PaperTradingSession, actor_ref: str, requested_at: str, policy: PaperRevalidationPolicy | None = None) -> PaperRevalidationRequest:
    selected = policy or PaperRevalidationPolicy()
    return PaperRevalidationRequest(revalidation_id, session.session_id, session.champion_version_id, selected.policy_version, requested_at, actor_ref)


def report_from_json(value: str) -> PaperRevalidationReport:
    payload = json.loads(value)
    return PaperRevalidationReport(
        revalidation_id=str(payload["revalidation_id"]),
        status=PaperRevalidationStatus(str(payload["status"])),
        policy_version=str(payload["policy_version"]),
        session_id=str(payload["session_id"]),
        champion_version_id=str(payload["champion_version_id"]),
        fingerprint=str(payload["fingerprint"]),
        rule_results=tuple(PaperRevalidationRuleResult(str(item["rule"]), RiskGateDecision(str(item["decision"])), str(item["observed"]), str(item["threshold"]), str(item["message"])) for item in payload["rule_results"]),
        warnings=tuple(str(item) for item in payload["warnings"]),
        kill_reasons=tuple(KillGateReason(str(item)) for item in payload["kill_reasons"]),
        rollback=RollbackRecommendation(**payload["rollback"]),
        generated_at=str(payload["generated_at"]),
    )


def _session_state_rule(session: PaperTradingSession, summary: PaperTradingPerformanceSummary) -> PaperRevalidationRuleResult:
    if session.status != summary.status:
        return _rule("session_state", RiskGateDecision.KILL, f"{session.status.value}/{summary.status.value}", "matching", "session and summary state mismatch")
    if session.status == PaperTradingSessionStatus.COMPLETED:
        return _rule("session_state", RiskGateDecision.PASS, session.status.value, "completed", "paper session completed")
    if session.status in {PaperTradingSessionStatus.FAILED, PaperTradingSessionStatus.CANCELLED}:
        return _rule("session_state", RiskGateDecision.KILL, session.status.value, "completed", "paper session ended in unsafe state")
    return _rule("session_state", RiskGateDecision.HOLD, session.status.value, "completed", "paper session is not complete")


def _fingerprint_rule(active: ChampionRegistryEntry, session: PaperTradingSession, summary: PaperTradingPerformanceSummary) -> PaperRevalidationRuleResult:
    if active.active_version_id != session.champion_version_id or active.fingerprint != session.fingerprint or session.fingerprint != summary.fingerprint:
        return _rule("champion_fingerprint", RiskGateDecision.KILL, f"{active.fingerprint}/{session.fingerprint}/{summary.fingerprint}", "all equal", "active Champion fingerprint mismatch")
    return _rule("champion_fingerprint", RiskGateDecision.PASS, session.fingerprint, "matches active", "Champion fingerprint remained unchanged")


def _trade_count_rule(summary: PaperTradingPerformanceSummary, policy: PaperRevalidationPolicy) -> PaperRevalidationRuleResult:
    if summary.simulated_orders < policy.minimum_simulated_trades:
        return _rule("simulated_trade_count", RiskGateDecision.HOLD, str(summary.simulated_orders), f">= {policy.minimum_simulated_trades}", "insufficient paper trade count")
    return _rule("simulated_trade_count", RiskGateDecision.PASS, str(summary.simulated_orders), f">= {policy.minimum_simulated_trades}", "paper trade count threshold met")


def _execution_error_rule(summary: PaperTradingPerformanceSummary) -> PaperRevalidationRuleResult:
    critical = summary.failed_simulated_orders + len(summary.errors)
    if critical > 0:
        return _rule("critical_execution_errors", RiskGateDecision.KILL, str(critical), "0", "critical paper execution error detected")
    return _rule("critical_execution_errors", RiskGateDecision.PASS, "0", "0", "no critical execution errors")


def _drawdown_rule(summary: PaperTradingPerformanceSummary, policy: PaperRevalidationPolicy) -> PaperRevalidationRuleResult:
    if summary.max_paper_drawdown is None:
        return _rule("paper_drawdown", RiskGateDecision.REVIEW, "missing", f"<= {policy.maximum_paper_drawdown:.2f}", "paper drawdown metric is unavailable")
    if summary.max_paper_drawdown < 0 or summary.max_paper_drawdown > 1:
        return _rule("paper_drawdown", RiskGateDecision.KILL, f"{summary.max_paper_drawdown:.4f}", "0..1", "impossible paper drawdown metric")
    if summary.max_paper_drawdown >= policy.hard_kill_paper_drawdown:
        return _rule("paper_drawdown", RiskGateDecision.KILL, f"{summary.max_paper_drawdown:.4f}", f"< {policy.hard_kill_paper_drawdown:.2f}", "paper drawdown exceeded hard kill threshold")
    if summary.max_paper_drawdown > policy.maximum_paper_drawdown:
        return _rule("paper_drawdown", RiskGateDecision.ROLLBACK_RECOMMENDED, f"{summary.max_paper_drawdown:.4f}", f"<= {policy.maximum_paper_drawdown:.2f}", "paper drawdown materially exceeded policy")
    return _rule("paper_drawdown", RiskGateDecision.PASS, f"{summary.max_paper_drawdown:.4f}", f"<= {policy.maximum_paper_drawdown:.2f}", "paper drawdown within policy")


def _rejection_rate_rule(summary: PaperTradingPerformanceSummary, policy: PaperRevalidationPolicy) -> PaperRevalidationRuleResult:
    if summary.simulated_orders == 0:
        return _rule("execution_rejection_rate", RiskGateDecision.HOLD, "missing", f"<= {policy.maximum_rejection_rate:.2f}", "rejection rate unavailable without paper orders")
    rate = summary.rejected_simulated_orders / summary.simulated_orders
    if rate > policy.maximum_rejection_rate:
        return _rule("execution_rejection_rate", RiskGateDecision.ROLLBACK_RECOMMENDED, f"{rate:.4f}", f"<= {policy.maximum_rejection_rate:.2f}", "paper rejection rate is elevated")
    return _rule("execution_rejection_rate", RiskGateDecision.PASS, f"{rate:.4f}", f"<= {policy.maximum_rejection_rate:.2f}", "paper rejection rate within policy")


def _missing_metric_rule(summary: PaperTradingPerformanceSummary) -> PaperRevalidationRuleResult:
    missing = [name for name, value in (("realized_paper_pnl", summary.realized_paper_pnl), ("unrealized_paper_pnl", summary.unrealized_paper_pnl), ("exposure", summary.exposure)) if value is None]
    if missing:
        return _rule("optional_metrics", RiskGateDecision.REVIEW, ",".join(missing), "record only", "optional paper metrics unavailable; values were not fabricated")
    return _rule("optional_metrics", RiskGateDecision.PASS, "available", "record only", "optional paper metrics available")


def _status(rules: tuple[PaperRevalidationRuleResult, ...]) -> PaperRevalidationStatus:
    if any(rule.decision == RiskGateDecision.KILL for rule in rules):
        return PaperRevalidationStatus.KILL
    if any(rule.decision == RiskGateDecision.ROLLBACK_RECOMMENDED for rule in rules):
        return PaperRevalidationStatus.ROLLBACK_RECOMMENDED
    if any(rule.decision == RiskGateDecision.HOLD for rule in rules):
        return PaperRevalidationStatus.HOLD
    if any(rule.decision == RiskGateDecision.REVIEW for rule in rules):
        return PaperRevalidationStatus.REVIEW
    return PaperRevalidationStatus.LIVE_ELIGIBLE


def _kill_reasons(rules: tuple[PaperRevalidationRuleResult, ...]) -> tuple[KillGateReason, ...]:
    mapping = {"critical_execution_errors": KillGateReason.CRITICAL_EXECUTION_ERROR, "session_state": KillGateReason.CORRUPTED_SESSION_STATE, "champion_fingerprint": KillGateReason.FINGERPRINT_MISMATCH, "paper_drawdown": KillGateReason.EXTREME_PAPER_DRAWDOWN}
    return tuple(mapping[rule.rule] for rule in rules if rule.decision == RiskGateDecision.KILL and rule.rule in mapping)


def _event_for_status(status: PaperRevalidationStatus) -> str:
    return {
        PaperRevalidationStatus.LIVE_ELIGIBLE: "LiveEligibilityGranted",
        PaperRevalidationStatus.HOLD: "PaperRiskHoldTriggered",
        PaperRevalidationStatus.KILL: "PaperKillGateTriggered",
        PaperRevalidationStatus.ROLLBACK_RECOMMENDED: "ChampionRollbackRecommended",
        PaperRevalidationStatus.REVIEW: "PaperRevalidationReviewRequired",
    }[status]


def _metric_for_status(status: PaperRevalidationStatus) -> str:
    return {
        PaperRevalidationStatus.LIVE_ELIGIBLE: "gaon_live_eligible_total",
        PaperRevalidationStatus.HOLD: "gaon_paper_hold_total",
        PaperRevalidationStatus.KILL: "gaon_paper_kill_total",
        PaperRevalidationStatus.ROLLBACK_RECOMMENDED: "gaon_rollback_recommended_total",
        PaperRevalidationStatus.REVIEW: "gaon_revalidation_review_total",
    }[status]


def _rule(rule: str, decision: RiskGateDecision, observed: str, threshold: str, message: str) -> PaperRevalidationRuleResult:
    return PaperRevalidationRuleResult(rule, decision, observed, threshold, message)


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="paper_revalidation")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
