"""Deterministic strategy validation engine for normalized backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import json
import sqlite3
from typing import Any

from gaon.adapters.backtest import BacktestResult, BacktestStatus


POLICY_VERSION = "validation_policy_v1"


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    REVIEW = "review"
    FAIL = "fail"


@dataclass(frozen=True)
class ValidationEvidence:
    evidence_id: str
    source_ref: str
    description: str


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    description: str
    severity: ValidationSeverity
    optional: bool = False


@dataclass(frozen=True)
class ValidationRuleResult:
    rule_id: str
    status: ValidationStatus
    severity: ValidationSeverity
    message: str
    observed: str
    threshold: str


@dataclass(frozen=True)
class ValidationPolicy:
    policy_version: str = POLICY_VERSION
    min_total_return: float = 0.0
    min_annualized_return: float | None = None
    min_profit_factor: float = 1.1
    max_drawdown: float = 0.30
    max_exposure: float | None = None
    min_trade_count: int = 30
    min_sample_days: int = 180
    min_win_rate: float | None = None
    missing_profit_factor_status: ValidationStatus = ValidationStatus.REVIEW
    missing_annualized_return_status: ValidationStatus = ValidationStatus.REVIEW
    require_fingerprint: bool = True
    min_passing_window_ratio: float = 0.8


@dataclass(frozen=True)
class ValidationRequest:
    validation_id: str
    backtest_result_ids: tuple[str, ...]
    policy_version: str
    requested_at: str
    actor_ref: str

    def __post_init__(self) -> None:
        if not self.validation_id or not self.backtest_result_ids or not self.policy_version or not self.requested_at or not self.actor_ref:
            raise ValueError("validation request requires id, results, policy, timestamp, and actor")

    def to_json(self) -> str:
        return _dumps(
            {
                "validation_id": self.validation_id,
                "backtest_result_ids": list(self.backtest_result_ids),
                "policy_version": self.policy_version,
                "requested_at": self.requested_at,
                "actor_ref": self.actor_ref,
            }
        )


@dataclass(frozen=True)
class ValidationReport:
    validation_id: str
    backtest_run_id: str
    fingerprint: str
    strategy_ref: str
    dataset_ref: str
    policy_version: str
    overall_status: ValidationStatus
    score: int
    rule_results: tuple[ValidationRuleResult, ...]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    unknowns: tuple[str, ...]
    generated_at: str
    reproducibility: dict[str, str]
    evidence: tuple[ValidationEvidence, ...] = ()

    def to_json(self) -> str:
        return _dumps(
            {
                "validation_id": self.validation_id,
                "backtest_run_id": self.backtest_run_id,
                "fingerprint": self.fingerprint,
                "strategy_ref": self.strategy_ref,
                "dataset_ref": self.dataset_ref,
                "policy_version": self.policy_version,
                "overall_status": self.overall_status.value,
                "score": self.score,
                "rule_results": [
                    {
                        "rule_id": rule.rule_id,
                        "status": rule.status.value,
                        "severity": rule.severity.value,
                        "message": rule.message,
                        "observed": rule.observed,
                        "threshold": rule.threshold,
                    }
                    for rule in self.rule_results
                ],
                "warnings": list(self.warnings),
                "failures": list(self.failures),
                "unknowns": list(self.unknowns),
                "generated_at": self.generated_at,
                "reproducibility": self.reproducibility,
                "evidence": [evidence.__dict__ for evidence in self.evidence],
            }
        )


class StrategyValidationEngine:
    def __init__(self, policy: ValidationPolicy | None = None, *, repository: "SQLiteValidationRepository | None" = None, event_store: Any | None = None, metrics: Any | None = None) -> None:
        self._policy = policy or ValidationPolicy()
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics

    @property
    def policy(self) -> ValidationPolicy:
        return self._policy

    def validate(self, request: ValidationRequest, results: tuple[BacktestResult, ...], *, generated_at: str) -> ValidationReport:
        self._record("ValidationRequested", request, None, generated_at)
        self._record("ValidationStarted", request, None, generated_at)
        _increment(self._metrics, "gaon_validation_requests_total")
        if self._repository is not None:
            self._repository.add_request(request)
        try:
            report = self._validate(request, results, generated_at=generated_at)
        except Exception:
            self._record("ValidationFailed", request, None, generated_at)
            _increment(self._metrics, "gaon_validation_errors_total")
            raise
        if self._repository is not None:
            self._repository.add_report(report)
        self._record("ValidationReviewRequired" if report.overall_status == ValidationStatus.REVIEW else "ValidationCompleted", request, report, generated_at)
        _increment(self._metrics, f"gaon_validation_{report.overall_status.value}_total")
        return report

    def _validate(self, request: ValidationRequest, results: tuple[BacktestResult, ...], *, generated_at: str) -> ValidationReport:
        if not results:
            raise ValueError("validation requires at least one backtest result")
        primary = results[0]
        rule_results: list[ValidationRuleResult] = []
        for result in results:
            rule_results.extend(_single_result_rules(result, self._policy))
        if len(results) > 1:
            rule_results.extend(_multi_result_rules(results, self._policy))
        rule_results.extend(_overfitting_warnings(results, self._policy))
        status = _overall_status(rule_results)
        score = _score(results, rule_results, self._policy)
        warnings = tuple(rule.message for rule in rule_results if rule.severity in {ValidationSeverity.WARNING, ValidationSeverity.REVIEW} and rule.status != ValidationStatus.PASS)
        failures = tuple(rule.message for rule in rule_results if rule.status == ValidationStatus.FAIL)
        unknowns = tuple(rule.message for rule in rule_results if rule.status == ValidationStatus.REVIEW and rule.observed == "missing")
        return ValidationReport(
            validation_id=request.validation_id,
            backtest_run_id=primary.result_id,
            fingerprint=primary.fingerprint,
            strategy_ref=f"{primary.strategy.strategy_id}:{primary.strategy.version}",
            dataset_ref=f"{primary.dataset.dataset_id}:{primary.dataset.version}",
            policy_version=self._policy.policy_version,
            overall_status=status,
            score=score,
            rule_results=tuple(rule_results),
            warnings=warnings,
            failures=failures,
            unknowns=unknowns,
            generated_at=generated_at,
            reproducibility=dict(primary.reproducibility),
            evidence=(ValidationEvidence(f"evidence:{primary.result_id}", primary.result_id, "normalized BacktestResult"),),
        )

    def _record(self, event_type: str, request: ValidationRequest, report: ValidationReport | None, at: str) -> None:
        if self._event_store is None:
            return
        self._event_store.append(validation_event(event_type, request, report, at))


class SQLiteValidationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: ValidationRequest) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO validation_requests(validation_id, policy_version, backtest_result_ids_json, payload_json, requested_at) VALUES (?, ?, ?, ?, ?)",
                (request.validation_id, request.policy_version, json.dumps(list(request.backtest_result_ids), sort_keys=True), request.to_json(), request.requested_at),
            )

    def add_report(self, report: ValidationReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO validation_reports(validation_id, backtest_run_id, fingerprint, status, score, policy_version, payload_json, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (report.validation_id, report.backtest_run_id, report.fingerprint, report.overall_status.value, report.score, report.policy_version, report.to_json(), report.generated_at),
            )

    def get_report(self, validation_id: str) -> ValidationReport:
        row = self._connection.execute("SELECT payload_json FROM validation_reports WHERE validation_id = ?", (validation_id,)).fetchone()
        if row is None:
            raise KeyError(validation_id)
        return report_from_json(str(row[0]))

    def list_reports(self) -> tuple[ValidationReport, ...]:
        rows = self._connection.execute("SELECT payload_json FROM validation_reports ORDER BY generated_at, validation_id").fetchall()
        return tuple(report_from_json(str(row[0])) for row in rows)


def build_validation_request(validation_id: str, results: tuple[BacktestResult, ...], *, actor_ref: str, requested_at: str, policy: ValidationPolicy | None = None) -> ValidationRequest:
    selected_policy = policy or ValidationPolicy()
    return ValidationRequest(validation_id, tuple(result.result_id for result in results), selected_policy.policy_version, requested_at, actor_ref)


def report_from_json(value: str) -> ValidationReport:
    payload = json.loads(value)
    return ValidationReport(
        validation_id=str(payload["validation_id"]),
        backtest_run_id=str(payload["backtest_run_id"]),
        fingerprint=str(payload["fingerprint"]),
        strategy_ref=str(payload["strategy_ref"]),
        dataset_ref=str(payload["dataset_ref"]),
        policy_version=str(payload["policy_version"]),
        overall_status=ValidationStatus(str(payload["overall_status"])),
        score=int(payload["score"]),
        rule_results=tuple(
            ValidationRuleResult(
                str(rule["rule_id"]),
                ValidationStatus(str(rule["status"])),
                ValidationSeverity(str(rule["severity"])),
                str(rule["message"]),
                str(rule["observed"]),
                str(rule["threshold"]),
            )
            for rule in payload["rule_results"]
        ),
        warnings=tuple(str(item) for item in payload["warnings"]),
        failures=tuple(str(item) for item in payload["failures"]),
        unknowns=tuple(str(item) for item in payload["unknowns"]),
        generated_at=str(payload["generated_at"]),
        reproducibility={str(key): str(value) for key, value in payload["reproducibility"].items()},
        evidence=tuple(ValidationEvidence(**item) for item in payload.get("evidence", ())),
    )


def validation_event(event_type: str, request: ValidationRequest, report: ValidationReport | None, at: str):
    from gaon.runtime.event_store import DurableEvent

    return DurableEvent(
        event_id=f"event:validation:{event_type}:{request.validation_id}",
        event_type=event_type,
        occurred_at=at,
        actor_ref=request.actor_ref,
        correlation_id=request.validation_id,
        causation_id=None,
        scope="validation",
        project="StrategyLab",
        strategy=report.strategy_ref if report else "N/A",
        market="N/A",
        payload={"validation_id": request.validation_id, "status": report.overall_status.value if report else "requested", "score": report.score if report else 0},
        evidence_refs=tuple(evidence.evidence_id for evidence in report.evidence) if report else (),
        audit_refs=(),
        appended_at=at,
    )


def normalize_drawdown(value: float | None) -> float:
    if value is None:
        raise ValueError("maximum drawdown is missing")
    if -1.0 <= value <= 0:
        return abs(value)
    if 0 <= value <= 1.0:
        return value
    if 1.0 < value <= 100.0:
        return value / 100.0
    raise ValueError("maximum drawdown is outside supported range")


def _single_result_rules(result: BacktestResult, policy: ValidationPolicy) -> list[ValidationRuleResult]:
    rules: list[ValidationRuleResult] = []
    metrics = result.metrics
    if result.status != BacktestStatus.COMPLETED:
        rules.append(_rule("completed_status", ValidationStatus.FAIL, ValidationSeverity.FAIL, "backtest result is not completed", result.status.value, "completed"))
    if policy.require_fingerprint and (not result.fingerprint or result.reproducibility.get("fingerprint") != result.fingerprint):
        rules.append(_rule("fingerprint_required", ValidationStatus.FAIL, ValidationSeverity.FAIL, "reproducibility fingerprint is missing or mismatched", result.fingerprint or "missing", "required"))
    rules.append(_threshold("total_return", metrics.total_return, policy.min_total_return, greater=True, missing=ValidationStatus.FAIL))
    rules.append(_threshold("profit_factor", metrics.profit_factor, policy.min_profit_factor, greater=True, missing=policy.missing_profit_factor_status))
    if policy.min_annualized_return is not None:
        rules.append(_threshold("annualized_return", metrics.annualized_return, policy.min_annualized_return, greater=True, missing=policy.missing_annualized_return_status))
    if policy.max_exposure is not None:
        rules.append(_threshold("exposure", metrics.exposure, policy.max_exposure, greater=False, missing=ValidationStatus.REVIEW))
    if policy.min_win_rate is not None:
        rules.append(_threshold("win_rate", metrics.win_rate, policy.min_win_rate, greater=True, missing=ValidationStatus.REVIEW))
    try:
        drawdown = normalize_drawdown(metrics.max_drawdown)
        rules.append(_rule("max_drawdown", ValidationStatus.PASS if drawdown <= policy.max_drawdown else ValidationStatus.FAIL, ValidationSeverity.FAIL, "maximum drawdown within policy" if drawdown <= policy.max_drawdown else "maximum drawdown exceeds policy", f"{drawdown:.4f}", f"<= {policy.max_drawdown:.4f}"))
    except ValueError as exc:
        rules.append(_rule("max_drawdown", ValidationStatus.FAIL, ValidationSeverity.FAIL, str(exc), str(metrics.max_drawdown), "valid drawdown"))
    trade_count = metrics.trade_count if metrics.trade_count is not None else result.trade_summary.trade_count
    rules.append(_rule("trade_count", ValidationStatus.PASS if trade_count >= policy.min_trade_count else ValidationStatus.FAIL, ValidationSeverity.FAIL, "trade count is sufficient" if trade_count >= policy.min_trade_count else "trade count is below policy minimum", str(trade_count), f">= {policy.min_trade_count}"))
    sample_days = _sample_days(metrics.start_date or result.period.start_date, metrics.end_date or result.period.end_date)
    rules.append(_rule("sample_period", ValidationStatus.PASS if sample_days >= policy.min_sample_days else ValidationStatus.REVIEW, ValidationSeverity.REVIEW, "sample period is sufficient" if sample_days >= policy.min_sample_days else "sample period is shorter than policy minimum", str(sample_days), f">= {policy.min_sample_days} days"))
    return rules


def _multi_result_rules(results: tuple[BacktestResult, ...], policy: ValidationPolicy) -> list[ValidationRuleResult]:
    per_window = [_overall_status(tuple(_single_result_rules(result, policy))) for result in results]
    pass_count = sum(1 for status in per_window if status == ValidationStatus.PASS)
    ratio = pass_count / len(results)
    catastrophic = any(_safe_drawdown(result) is not None and _safe_drawdown(result) > policy.max_drawdown * 1.5 for result in results)
    rules = [_rule("passing_window_ratio", ValidationStatus.PASS if ratio >= policy.min_passing_window_ratio else ValidationStatus.REVIEW, ValidationSeverity.REVIEW, "validation window pass ratio is acceptable" if ratio >= policy.min_passing_window_ratio else "validation window pass ratio requires review", f"{ratio:.2f}", f">= {policy.min_passing_window_ratio:.2f}")]
    if catastrophic:
        rules.append(_rule("catastrophic_window", ValidationStatus.FAIL, ValidationSeverity.FAIL, "at least one validation window has catastrophic drawdown", "present", "absent"))
    return rules


def _overfitting_warnings(results: tuple[BacktestResult, ...], policy: ValidationPolicy) -> list[ValidationRuleResult]:
    rules: list[ValidationRuleResult] = []
    for result in results:
        trade_count = result.metrics.trade_count if result.metrics.trade_count is not None else result.trade_summary.trade_count
        if result.metrics.total_return is not None and result.metrics.total_return > 1.0 and trade_count < policy.min_trade_count:
            rules.append(_rule("overfit_high_return_low_trades", ValidationStatus.REVIEW, ValidationSeverity.WARNING, "very high return with low trade count is an overfitting warning, not proof", f"return={result.metrics.total_return:.2f}, trades={trade_count}", "review"))
        if result.metrics.win_rate is not None and result.metrics.win_rate > 0.9 and trade_count < policy.min_trade_count:
            rules.append(_rule("overfit_high_win_rate_low_trades", ValidationStatus.REVIEW, ValidationSeverity.WARNING, "very high win rate with tiny sample is an overfitting warning, not proof", f"win_rate={result.metrics.win_rate:.2f}, trades={trade_count}", "review"))
    if len(results) > 1:
        returns = [result.metrics.total_return for result in results if result.metrics.total_return is not None]
        if returns and max(returns) > max(0.01, sum(returns)) * 0.8:
            rules.append(_rule("one_window_dominates", ValidationStatus.REVIEW, ValidationSeverity.WARNING, "one window dominates aggregate return", f"max={max(returns):.4f}", "balanced windows"))
    return rules


def _safe_drawdown(result: BacktestResult) -> float | None:
    try:
        return normalize_drawdown(result.metrics.max_drawdown)
    except ValueError:
        return None


def _threshold(rule_id: str, observed: float | None, threshold: float, *, greater: bool, missing: ValidationStatus) -> ValidationRuleResult:
    if observed is None:
        severity = ValidationSeverity.FAIL if missing == ValidationStatus.FAIL else ValidationSeverity.REVIEW
        return _rule(rule_id, missing, severity, f"{rule_id} is missing", "missing", str(threshold))
    ok = observed >= threshold if greater else observed <= threshold
    return _rule(rule_id, ValidationStatus.PASS if ok else ValidationStatus.FAIL, ValidationSeverity.FAIL, f"{rule_id} within policy" if ok else f"{rule_id} violates policy", f"{observed:.4f}", (">= " if greater else "<= ") + f"{threshold:.4f}")


def _rule(rule_id: str, status: ValidationStatus, severity: ValidationSeverity, message: str, observed: str, threshold: str) -> ValidationRuleResult:
    return ValidationRuleResult(rule_id, status, severity, message, observed, threshold)


def _overall_status(rules: tuple[ValidationRuleResult, ...] | list[ValidationRuleResult]) -> ValidationStatus:
    if any(rule.status == ValidationStatus.FAIL for rule in rules):
        return ValidationStatus.FAIL
    if any(rule.status == ValidationStatus.REVIEW for rule in rules):
        return ValidationStatus.REVIEW
    return ValidationStatus.PASS


def _score(results: tuple[BacktestResult, ...], rules: list[ValidationRuleResult], policy: ValidationPolicy) -> int:
    primary = results[0]
    trade_count = primary.metrics.trade_count if primary.metrics.trade_count is not None else primary.trade_summary.trade_count
    drawdown = _safe_drawdown(primary)
    dimensions = [
        _cap((primary.metrics.total_return or 0.0) / max(policy.min_total_return, 0.01), 1.0),
        1.0 - _cap((drawdown or policy.max_drawdown) / max(policy.max_drawdown, 0.01), 1.0),
        _cap(trade_count / max(policy.min_trade_count, 1), 1.0),
        _cap((primary.metrics.profit_factor or 0.0) / max(policy.min_profit_factor, 0.01), 1.0),
        _cap(_sample_days(primary.metrics.start_date or primary.period.start_date, primary.metrics.end_date or primary.period.end_date) / policy.min_sample_days, 1.0),
        1.0 if primary.fingerprint and primary.reproducibility.get("fingerprint") == primary.fingerprint else 0.0,
    ]
    score = round(sum(dimensions) / len(dimensions) * 100)
    if any(rule.status == ValidationStatus.FAIL for rule in rules):
        score = min(score, 69)
    return max(0, min(100, score))


def _sample_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _cap(value: float, max_value: float) -> float:
    return max(0.0, min(max_value, value))


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="validation")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
