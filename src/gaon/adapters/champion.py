"""Deterministic Champion / Challenger evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import json
import sqlite3
from typing import Any

from gaon.adapters.backtest import BacktestResult
from gaon.adapters.validation import ValidationReport, ValidationStatus, normalize_drawdown


POLICY_VERSION = "champion_challenger_policy_v1"


class StrategyRole(str, Enum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"


class ChampionChallengerDecision(str, Enum):
    KEEP_CHAMPION = "keep_champion"
    PROMOTION_CANDIDATE = "promotion_candidate"
    REVIEW = "review"


class ComparisonStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class ChampionChallengerPolicy:
    policy_version: str = POLICY_VERSION
    minimum_return_improvement: float = 0.05
    maximum_mdd_degradation: float = 0.05
    require_profit_factor_not_worse: bool = True
    sample_period_review_ratio: float = 0.50


@dataclass(frozen=True)
class ChampionChallengerEvaluationRequest:
    evaluation_id: str
    champion_backtest_id: str
    challenger_backtest_id: str
    validation_id: str
    policy_version: str
    requested_at: str
    actor_ref: str

    def __post_init__(self) -> None:
        if not all((self.evaluation_id, self.champion_backtest_id, self.challenger_backtest_id, self.validation_id, self.policy_version, self.requested_at, self.actor_ref)):
            raise ValueError("champion/challenger evaluation request is incomplete")

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class ChampionChallengerMetricComparison:
    metric: str
    status: ComparisonStatus
    champion_value: str
    challenger_value: str
    difference: str
    threshold: str
    message: str


@dataclass(frozen=True)
class ChampionChallengerEvaluationReport:
    evaluation_id: str
    decision: ChampionChallengerDecision
    policy_version: str
    evaluation_score: int
    champion_backtest_id: str
    challenger_backtest_id: str
    validation_id: str
    champion_fingerprint: str
    challenger_fingerprint: str
    comparisons: tuple[ChampionChallengerMetricComparison, ...]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    generated_at: str
    rationale: str

    def to_json(self) -> str:
        return _dumps(
            {
                "evaluation_id": self.evaluation_id,
                "decision": self.decision.value,
                "policy_version": self.policy_version,
                "evaluation_score": self.evaluation_score,
                "champion_backtest_id": self.champion_backtest_id,
                "challenger_backtest_id": self.challenger_backtest_id,
                "validation_id": self.validation_id,
                "champion_fingerprint": self.champion_fingerprint,
                "challenger_fingerprint": self.challenger_fingerprint,
                "comparisons": [comparison.__dict__ | {"status": comparison.status.value} for comparison in self.comparisons],
                "warnings": list(self.warnings),
                "failures": list(self.failures),
                "generated_at": self.generated_at,
                "rationale": self.rationale,
            }
        )


class ChampionChallengerEvaluationEngine:
    def __init__(self, policy: ChampionChallengerPolicy | None = None, *, repository: "SQLiteChampionChallengerRepository | None" = None, event_store: Any | None = None, metrics: Any | None = None) -> None:
        self._policy = policy or ChampionChallengerPolicy()
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics

    @property
    def policy(self) -> ChampionChallengerPolicy:
        return self._policy

    def evaluate(
        self,
        request: ChampionChallengerEvaluationRequest,
        *,
        champion: BacktestResult,
        challenger: BacktestResult,
        validation: ValidationReport,
        generated_at: str,
    ) -> ChampionChallengerEvaluationReport:
        self._record("ChampionChallengerEvaluationRequested", request, None, generated_at)
        _increment(self._metrics, "champion_challenger_evaluations_total")
        if self._repository is not None:
            self._repository.add_request(request)
        report = self._evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=generated_at)
        if self._repository is not None:
            self._repository.add_report(report)
        event_type = {
            ChampionChallengerDecision.PROMOTION_CANDIDATE: "PromotionCandidateIdentified",
            ChampionChallengerDecision.KEEP_CHAMPION: "ChampionRetained",
            ChampionChallengerDecision.REVIEW: "ChampionChallengerReviewRequired",
        }[report.decision]
        self._record("ChampionChallengerEvaluationCompleted", request, report, generated_at)
        self._record(event_type, request, report, generated_at)
        _increment(
            self._metrics,
            {
                ChampionChallengerDecision.PROMOTION_CANDIDATE: "promotion_candidates_total",
                ChampionChallengerDecision.KEEP_CHAMPION: "champion_retained_total",
                ChampionChallengerDecision.REVIEW: "champion_challenger_reviews_total",
            }[report.decision],
        )
        return report

    def _evaluate(self, request: ChampionChallengerEvaluationRequest, *, champion: BacktestResult, challenger: BacktestResult, validation: ValidationReport, generated_at: str) -> ChampionChallengerEvaluationReport:
        comparisons = [
            _validation_gate(validation),
            _fingerprint_gate(champion, challenger),
            _return_comparison(champion, challenger, self._policy),
            _drawdown_comparison(champion, challenger, self._policy),
            _profit_factor_comparison(champion, challenger, self._policy),
            _sample_comparison(champion, challenger, self._policy),
            _trade_count_comparison(champion, challenger),
        ]
        decision = _decision(comparisons)
        score = _score(comparisons)
        failures = tuple(comparison.message for comparison in comparisons if comparison.status == ComparisonStatus.FAIL)
        warnings = tuple(comparison.message for comparison in comparisons if comparison.status in {ComparisonStatus.REVIEW, ComparisonStatus.NOT_EVALUATED})
        return ChampionChallengerEvaluationReport(
            evaluation_id=request.evaluation_id,
            decision=decision,
            policy_version=self._policy.policy_version,
            evaluation_score=score,
            champion_backtest_id=champion.result_id,
            challenger_backtest_id=challenger.result_id,
            validation_id=validation.validation_id,
            champion_fingerprint=champion.fingerprint,
            challenger_fingerprint=challenger.fingerprint,
            comparisons=tuple(comparisons),
            warnings=warnings,
            failures=failures,
            generated_at=generated_at,
            rationale=_rationale(decision),
        )

    def _record(self, event_type: str, request: ChampionChallengerEvaluationRequest, report: ChampionChallengerEvaluationReport | None, at: str) -> None:
        if self._event_store is not None:
            try:
                self._event_store.append(champion_challenger_event(event_type, request, report, at))
            except sqlite3.IntegrityError:
                return


class SQLiteChampionChallengerRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: ChampionChallengerEvaluationRequest) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO champion_challenger_evaluation_requests(evaluation_id, champion_backtest_id, challenger_backtest_id, validation_id, policy_version, payload_json, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request.evaluation_id, request.champion_backtest_id, request.challenger_backtest_id, request.validation_id, request.policy_version, request.to_json(), request.requested_at),
            )

    def add_report(self, report: ChampionChallengerEvaluationReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO champion_challenger_evaluation_reports(evaluation_id, decision, policy_version, score, champion_backtest_id, challenger_backtest_id, validation_id, payload_json, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (report.evaluation_id, report.decision.value, report.policy_version, report.evaluation_score, report.champion_backtest_id, report.challenger_backtest_id, report.validation_id, report.to_json(), report.generated_at),
            )

    def get_report(self, evaluation_id: str) -> ChampionChallengerEvaluationReport:
        row = self._connection.execute("SELECT payload_json FROM champion_challenger_evaluation_reports WHERE evaluation_id = ?", (evaluation_id,)).fetchone()
        if row is None:
            raise KeyError(evaluation_id)
        return report_from_json(str(row[0]))

    def list_reports(self) -> tuple[ChampionChallengerEvaluationReport, ...]:
        rows = self._connection.execute("SELECT payload_json FROM champion_challenger_evaluation_reports ORDER BY generated_at, evaluation_id").fetchall()
        return tuple(report_from_json(str(row[0])) for row in rows)


def build_champion_challenger_request(evaluation_id: str, *, champion: BacktestResult, challenger: BacktestResult, validation: ValidationReport, actor_ref: str, requested_at: str, policy: ChampionChallengerPolicy | None = None) -> ChampionChallengerEvaluationRequest:
    selected_policy = policy or ChampionChallengerPolicy()
    return ChampionChallengerEvaluationRequest(evaluation_id, champion.result_id, challenger.result_id, validation.validation_id, selected_policy.policy_version, requested_at, actor_ref)


def report_from_json(value: str) -> ChampionChallengerEvaluationReport:
    payload = json.loads(value)
    return ChampionChallengerEvaluationReport(
        evaluation_id=str(payload["evaluation_id"]),
        decision=ChampionChallengerDecision(str(payload["decision"])),
        policy_version=str(payload["policy_version"]),
        evaluation_score=int(payload["evaluation_score"]),
        champion_backtest_id=str(payload["champion_backtest_id"]),
        challenger_backtest_id=str(payload["challenger_backtest_id"]),
        validation_id=str(payload["validation_id"]),
        champion_fingerprint=str(payload["champion_fingerprint"]),
        challenger_fingerprint=str(payload["challenger_fingerprint"]),
        comparisons=tuple(
            ChampionChallengerMetricComparison(
                metric=str(item["metric"]),
                status=ComparisonStatus(str(item["status"])),
                champion_value=str(item["champion_value"]),
                challenger_value=str(item["challenger_value"]),
                difference=str(item["difference"]),
                threshold=str(item["threshold"]),
                message=str(item["message"]),
            )
            for item in payload["comparisons"]
        ),
        warnings=tuple(str(item) for item in payload["warnings"]),
        failures=tuple(str(item) for item in payload["failures"]),
        generated_at=str(payload["generated_at"]),
        rationale=str(payload["rationale"]),
    )


def champion_challenger_event(event_type: str, request: ChampionChallengerEvaluationRequest, report: ChampionChallengerEvaluationReport | None, at: str):
    from gaon.runtime.event_store import DurableEvent

    return DurableEvent(
        event_id=f"event:champion-challenger:{event_type}:{request.evaluation_id}",
        event_type=event_type,
        occurred_at=at,
        actor_ref=request.actor_ref,
        correlation_id=request.evaluation_id,
        causation_id=request.validation_id,
        scope="champion_challenger_evaluation",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"evaluation_id": request.evaluation_id, "decision": report.decision.value if report else "requested", "score": report.evaluation_score if report else 0},
        evidence_refs=(request.validation_id,),
        audit_refs=(),
        appended_at=at,
    )


def _validation_gate(validation: ValidationReport) -> ChampionChallengerMetricComparison:
    if validation.overall_status == ValidationStatus.PASS:
        return _comparison("validation_status", ComparisonStatus.PASS, "N/A", validation.overall_status.value, "N/A", "pass", "challenger validation passed")
    if validation.overall_status == ValidationStatus.FAIL:
        return _comparison("validation_status", ComparisonStatus.FAIL, "N/A", validation.overall_status.value, "N/A", "pass", "challenger validation failed")
    return _comparison("validation_status", ComparisonStatus.REVIEW, "N/A", validation.overall_status.value, "N/A", "pass", "challenger validation requires review")


def _fingerprint_gate(champion: BacktestResult, challenger: BacktestResult) -> ChampionChallengerMetricComparison:
    if not champion.fingerprint or not challenger.fingerprint:
        return _comparison("fingerprint", ComparisonStatus.REVIEW, champion.fingerprint or "missing", challenger.fingerprint or "missing", "N/A", "both present", "comparison requires both fingerprints")
    if champion.fingerprint == challenger.fingerprint:
        return _comparison("fingerprint", ComparisonStatus.FAIL, champion.fingerprint, challenger.fingerprint, "0", "different", "champion and challenger fingerprints are identical")
    return _comparison("fingerprint", ComparisonStatus.PASS, champion.fingerprint, challenger.fingerprint, "different", "different", "fingerprints are comparable and different")


def _return_comparison(champion: BacktestResult, challenger: BacktestResult, policy: ChampionChallengerPolicy) -> ChampionChallengerMetricComparison:
    champion_return = champion.metrics.total_return
    challenger_return = challenger.metrics.total_return
    if champion_return is None or challenger_return is None:
        return _comparison("total_return", ComparisonStatus.REVIEW, _fmt(champion_return), _fmt(challenger_return), "missing", f">= +{policy.minimum_return_improvement:.4f}", "return comparison requires both total return metrics")
    diff = challenger_return - champion_return
    status = ComparisonStatus.PASS if diff >= policy.minimum_return_improvement else ComparisonStatus.FAIL
    return _comparison("total_return", status, _fmt(champion_return), _fmt(challenger_return), _fmt(diff, signed=True), f">= +{policy.minimum_return_improvement:.4f}", "challenger return improvement meets threshold" if status == ComparisonStatus.PASS else "challenger return improvement is insufficient")


def _drawdown_comparison(champion: BacktestResult, challenger: BacktestResult, policy: ChampionChallengerPolicy) -> ChampionChallengerMetricComparison:
    try:
        champion_mdd = normalize_drawdown(champion.metrics.max_drawdown)
        challenger_mdd = normalize_drawdown(challenger.metrics.max_drawdown)
    except ValueError as exc:
        return _comparison("max_drawdown", ComparisonStatus.REVIEW, str(champion.metrics.max_drawdown), str(challenger.metrics.max_drawdown), "missing", "valid mdd", str(exc))
    allowed = champion_mdd + policy.maximum_mdd_degradation
    status = ComparisonStatus.PASS if challenger_mdd <= allowed else ComparisonStatus.FAIL
    return _comparison("max_drawdown", status, _fmt(champion_mdd), _fmt(challenger_mdd), _fmt(challenger_mdd - champion_mdd, signed=True), f"<= {allowed:.4f}", "challenger drawdown is within allowed degradation" if status == ComparisonStatus.PASS else "challenger drawdown degradation exceeds threshold")


def _profit_factor_comparison(champion: BacktestResult, challenger: BacktestResult, policy: ChampionChallengerPolicy) -> ChampionChallengerMetricComparison:
    champion_pf = champion.metrics.profit_factor
    challenger_pf = challenger.metrics.profit_factor
    if champion_pf is None or challenger_pf is None:
        return _comparison("profit_factor", ComparisonStatus.NOT_EVALUATED, _fmt(champion_pf), _fmt(challenger_pf), "missing", "both present", "profit factor comparison was not evaluated because a metric is missing")
    status = ComparisonStatus.PASS if not policy.require_profit_factor_not_worse or challenger_pf >= champion_pf else ComparisonStatus.FAIL
    return _comparison("profit_factor", status, _fmt(champion_pf), _fmt(challenger_pf), _fmt(challenger_pf - champion_pf, signed=True), ">= champion", "challenger profit factor is acceptable" if status == ComparisonStatus.PASS else "challenger profit factor is worse than champion")


def _sample_comparison(champion: BacktestResult, challenger: BacktestResult, policy: ChampionChallengerPolicy) -> ChampionChallengerMetricComparison:
    champion_days = _sample_days(champion)
    challenger_days = _sample_days(challenger)
    shorter = min(champion_days, challenger_days)
    longer = max(champion_days, challenger_days)
    status = ComparisonStatus.PASS if longer == 0 or shorter / longer >= policy.sample_period_review_ratio else ComparisonStatus.REVIEW
    return _comparison("sample_period", status, str(champion_days), str(challenger_days), str(challenger_days - champion_days), f">= {policy.sample_period_review_ratio:.2f} ratio", "sample periods are broadly comparable" if status == ComparisonStatus.PASS else "sample period comparability requires review")


def _trade_count_comparison(champion: BacktestResult, challenger: BacktestResult) -> ChampionChallengerMetricComparison:
    champion_count = champion.metrics.trade_count if champion.metrics.trade_count is not None else champion.trade_summary.trade_count
    challenger_count = challenger.metrics.trade_count if challenger.metrics.trade_count is not None else challenger.trade_summary.trade_count
    return _comparison("trade_count", ComparisonStatus.PASS, str(champion_count), str(challenger_count), str(challenger_count - champion_count), "record only", "trade counts recorded for audit")


def _decision(comparisons: list[ChampionChallengerMetricComparison]) -> ChampionChallengerDecision:
    validation = _by_metric(comparisons, "validation_status")
    if validation.status == ComparisonStatus.FAIL:
        return ChampionChallengerDecision.KEEP_CHAMPION
    if validation.status == ComparisonStatus.REVIEW:
        return ChampionChallengerDecision.REVIEW
    if any(comparison.status == ComparisonStatus.REVIEW for comparison in comparisons):
        return ChampionChallengerDecision.REVIEW
    if any(comparison.status == ComparisonStatus.NOT_EVALUATED for comparison in comparisons):
        return ChampionChallengerDecision.REVIEW
    if any(comparison.status == ComparisonStatus.FAIL for comparison in comparisons):
        return ChampionChallengerDecision.KEEP_CHAMPION
    return ChampionChallengerDecision.PROMOTION_CANDIDATE


def _score(comparisons: list[ChampionChallengerMetricComparison]) -> int:
    weights = {ComparisonStatus.PASS: 1.0, ComparisonStatus.NOT_EVALUATED: 0.5, ComparisonStatus.REVIEW: 0.35, ComparisonStatus.FAIL: 0.0}
    score = round(sum(weights[comparison.status] for comparison in comparisons) / len(comparisons) * 100)
    if any(comparison.status == ComparisonStatus.FAIL for comparison in comparisons):
        score = min(score, 69)
    return max(0, min(100, score))


def _rationale(decision: ChampionChallengerDecision) -> str:
    if decision == ChampionChallengerDecision.PROMOTION_CANDIDATE:
        return "challenger passed validation and all comparison gates; this is not promotion"
    if decision == ChampionChallengerDecision.REVIEW:
        return "comparison requires human review before any future promotion workflow"
    return "champion remains selected by evaluation policy"


def _by_metric(comparisons: list[ChampionChallengerMetricComparison], metric: str) -> ChampionChallengerMetricComparison:
    for comparison in comparisons:
        if comparison.metric == metric:
            return comparison
    raise KeyError(metric)


def _sample_days(result: BacktestResult) -> int:
    start = result.metrics.start_date or result.period.start_date
    end = result.metrics.end_date or result.period.end_date
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _comparison(metric: str, status: ComparisonStatus, champion_value: str, challenger_value: str, difference: str, threshold: str, message: str) -> ChampionChallengerMetricComparison:
    return ChampionChallengerMetricComparison(metric, status, champion_value, challenger_value, difference, threshold, message)


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "missing"
    return f"{value:+.4f}" if signed else f"{value:.4f}"


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="champion_challenger")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
