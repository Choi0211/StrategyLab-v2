"""Approval-gated research operations for Sprint 121-130.

This module turns structured backtest evidence into advisory configuration
change proposals. It never places orders, promotes Champions automatically, or
touches private trading systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import re
import sqlite3
from typing import Any


SCHEMA_VERSION = 1
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REF_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,159}$")
ARTIFACT_MARKERS = (
    "research-ops-release-check:",
    "research-recommendation:research-ops-release-check:",
    "research-ops-demo:",
    "research-recommendation:research-ops-demo:",
    "test:",
    "unit:",
    "integration:",
)


class QualityStatus(str, Enum):
    PASS = "pass"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    FAIL = "fail"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DominanceDecision(str, Enum):
    DOMINATES = "dominates"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class RecommendationDecision(str, Enum):
    HOLD = "hold"
    RECOMMEND_CHALLENGER = "recommend_challenger"
    NEEDS_RETEST = "needs_retest"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class BacktestEvidence:
    result_id: str
    strategy_ref: str
    period_start: str
    period_end: str
    source: str
    fixture_backed: bool
    metrics: dict[str, float | int | None]
    quality_status: str
    provider_gap_count: int = 0
    blocking_findings: int = 0

    @property
    def trade_count(self) -> int:
        value = self.metrics.get("trade_count", 0)
        return int(value or 0)

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"trade_count": self.trade_count}


@dataclass(frozen=True)
class ResearchQualityGate:
    status: QualityStatus
    trade_count: int
    min_trades: int
    evidence_source: str
    fixture_backed: bool
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"status": self.status.value, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class StatisticalConfidence:
    level: ConfidenceLevel
    score: float
    trade_count: int
    win_rate: float | None
    profit_factor: float | None
    mdd: float | None
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"level": self.level.value, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class CandidateDominance:
    decision: DominanceDecision
    champion_result_id: str
    challenger_result_id: str
    return_delta: float | None
    mdd_delta: float | None
    profit_factor_delta: float | None
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"decision": self.decision.value, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class ResearchPeriodPlan:
    status: str
    requested_start: str
    requested_end: str
    expanded_start: str
    expanded_end: str
    expansion_required: bool
    reason: str

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class PromotionRecommendation:
    recommendation_id: str
    decision: RecommendationDecision
    approval_required: bool
    champion_result_id: str
    challenger_result_id: str
    proposed_config: dict[str, object]
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"decision": self.decision.value, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class StrategyConfigVersion:
    config_id: str
    slot: str
    revision: int
    strategy_ref: str
    parameters: dict[str, object]
    source_recommendation_id: str
    status: ApprovalStatus
    created_at: str
    previous_config_id: str | None
    rollback_ref: str | None

    def to_json(self) -> dict[str, object]:
        return self.__dict__ | {"status": self.status.value}


@dataclass(frozen=True)
class ResearchOperationReport:
    report_id: str
    generated_at: str
    champion: BacktestEvidence
    challenger: BacktestEvidence
    quality_gate: ResearchQualityGate
    confidence: StatisticalConfidence
    dominance: CandidateDominance
    period_plan: ResearchPeriodPlan
    recommendation: PromotionRecommendation
    config_version: StrategyConfigVersion | None
    rollback_available: bool
    audit_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "champion": self.champion.to_json(),
            "challenger": self.challenger.to_json(),
            "quality_gate": self.quality_gate.to_json(),
            "confidence": self.confidence.to_json(),
            "dominance": self.dominance.to_json(),
            "period_plan": self.period_plan.to_json(),
            "recommendation": self.recommendation.to_json(),
            "config_version": self.config_version.to_json() if self.config_version else None,
            "rollback_available": self.rollback_available,
            "audit_refs": list(self.audit_refs),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "approval_required_before_config_change": True,
        }


@dataclass(frozen=True)
class ResearchOpsCleanupPlan:
    report_ids: tuple[str, ...]
    approval_ids: tuple[str, ...]
    config_ids: tuple[str, ...]
    audit_ids: tuple[str, ...]

    @property
    def total(self) -> int:
        return len(self.report_ids) + len(self.approval_ids) + len(self.config_ids) + len(self.audit_ids)

    def to_json(self) -> dict[str, object]:
        return {
            "report_ids": list(self.report_ids),
            "approval_ids": list(self.approval_ids),
            "config_ids": list(self.config_ids),
            "audit_ids": list(self.audit_ids),
            "total": self.total,
        }


class SQLiteResearchOperationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_report(self, report: ResearchOperationReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO research_operation_reports(report_id, recommendation_id, status, payload_json, generated_at) VALUES (?, ?, ?, ?, ?)",
                (report.report_id, report.recommendation.recommendation_id, report.recommendation.decision.value, _dumps(report.to_json()), report.generated_at),
            )

    def get_report(self, report_id: str) -> ResearchOperationReport | None:
        row = self._connection.execute("SELECT payload_json FROM research_operation_reports WHERE report_id = ?", (report_id,)).fetchone()
        return report_from_json(str(row[0])) if row else None

    def list_reports(self, *, include_artifacts: bool = False) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute("SELECT report_id, recommendation_id, status, generated_at, payload_json FROM research_operation_reports ORDER BY generated_at, report_id").fetchall()
        reports: list[dict[str, object]] = []
        for row in rows:
            report_id = str(row[0])
            recommendation_id = str(row[1])
            payload = str(row[4])
            if not include_artifacts and _is_artifact_text(report_id, recommendation_id, payload):
                continue
            reports.append({"report_id": report_id, "recommendation_id": recommendation_id, "status": str(row[2]), "generated_at": str(row[3])})
        return tuple(reports)

    def add_approval(self, recommendation_id: str, status: ApprovalStatus, *, actor_ref: str, decided_at: str, reason: str) -> str:
        approval_id = f"research-config-approval:{recommendation_id}:{status.value}"
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO research_config_approvals(approval_id, recommendation_id, status, actor_ref, reason, decided_at, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (approval_id, recommendation_id, status.value, actor_ref, reason, decided_at, _dumps({"approval_id": approval_id, "recommendation_id": recommendation_id, "status": status.value, "actor_ref": actor_ref, "reason": reason, "decided_at": decided_at})),
            )
        return approval_id

    def approval_status(self, recommendation_id: str) -> ApprovalStatus | None:
        row = self._connection.execute("SELECT status FROM research_config_approvals WHERE recommendation_id = ? ORDER BY decided_at DESC, approval_id DESC LIMIT 1", (recommendation_id,)).fetchone()
        return ApprovalStatus(str(row[0])) if row else None

    def add_config(self, version: StrategyConfigVersion) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_config_versions(config_id, slot, revision, status, strategy_ref, payload_json, created_at, previous_config_id, rollback_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (version.config_id, version.slot, version.revision, version.status.value, version.strategy_ref, _dumps(version.to_json()), version.created_at, version.previous_config_id, version.rollback_ref),
            )

    def active_config(self, slot: str = "default", *, include_artifacts: bool = False) -> StrategyConfigVersion | None:
        rows = self._connection.execute("SELECT payload_json FROM strategy_config_versions WHERE slot = ? AND status = ? ORDER BY revision DESC, created_at DESC", (slot, ApprovalStatus.APPLIED.value)).fetchall()
        for row in rows:
            config = config_from_json(str(row[0]))
            if include_artifacts or not _is_artifact_config(config):
                return config
        return None

    def latest_config(self, slot: str = "default", *, include_artifacts: bool = False) -> StrategyConfigVersion | None:
        rows = self._connection.execute("SELECT payload_json FROM strategy_config_versions WHERE slot = ? ORDER BY revision DESC, created_at DESC", (slot,)).fetchall()
        for row in rows:
            config = config_from_json(str(row[0]))
            if include_artifacts or not _is_artifact_config(config):
                return config
        return None

    def append_audit(self, event_type: str, target_ref: str, payload: dict[str, object], created_at: str) -> str:
        audit_id = f"research-config-audit:{target_ref}:{event_type}:{created_at}".replace(" ", "_")
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_config_audit(audit_id, event_type, target_ref, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (audit_id, event_type, target_ref, _dumps(payload | {"audit_id": audit_id}), created_at),
            )
        return audit_id

    def audit_history(self, target_ref: str | None = None) -> tuple[dict[str, object], ...]:
        if target_ref is None:
            rows = self._connection.execute("SELECT audit_id, event_type, target_ref, created_at FROM strategy_config_audit ORDER BY created_at, audit_id").fetchall()
        else:
            rows = self._connection.execute("SELECT audit_id, event_type, target_ref, created_at FROM strategy_config_audit WHERE target_ref = ? ORDER BY created_at, audit_id", (target_ref,)).fetchall()
        return tuple({"audit_id": str(row[0]), "event_type": str(row[1]), "target_ref": str(row[2]), "created_at": str(row[3])} for row in rows)

    def cleanup_plan(self) -> ResearchOpsCleanupPlan:
        report_ids = _artifact_ids(
            self._connection.execute("SELECT report_id, recommendation_id, payload_json FROM research_operation_reports ORDER BY generated_at, report_id").fetchall(),
            0,
        )
        approval_ids = _artifact_ids(
            self._connection.execute("SELECT approval_id, recommendation_id, payload_json FROM research_config_approvals ORDER BY decided_at, approval_id").fetchall(),
            0,
        )
        config_rows = self._connection.execute("SELECT config_id, payload_json FROM strategy_config_versions ORDER BY revision, config_id").fetchall()
        config_ids = tuple(str(row[0]) for row in config_rows if _is_artifact_text(str(row[0]), str(row[1])))
        artifact_config_ids = set(config_ids)
        audit_rows = self._connection.execute("SELECT audit_id, event_type, target_ref, payload_json FROM strategy_config_audit ORDER BY created_at, audit_id").fetchall()
        audit_ids: list[str] = []
        for row in audit_rows:
            audit_id = str(row[0])
            event_type = str(row[1])
            target_ref = str(row[2])
            payload = str(row[3])
            if event_type == "artifact_cleanup":
                continue
            if target_ref in artifact_config_ids or _is_artifact_text(audit_id, target_ref, payload):
                audit_ids.append(audit_id)
        return ResearchOpsCleanupPlan(report_ids, approval_ids, config_ids, tuple(audit_ids))

    def cleanup_artifacts(self, *, apply: bool, actor_ref: str, created_at: str) -> ResearchOpsCleanupPlan:
        _validate_utc(created_at)
        plan = self.cleanup_plan()
        if not apply:
            return plan
        with self._connection:
            _delete_ids(self._connection, "strategy_config_versions", "config_id", plan.config_ids)
            _delete_ids(self._connection, "strategy_config_audit", "audit_id", plan.audit_ids)
            _delete_ids(self._connection, "research_config_approvals", "approval_id", plan.approval_ids)
            _delete_ids(self._connection, "research_operation_reports", "report_id", plan.report_ids)
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_config_audit(audit_id, event_type, target_ref, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"research-config-audit:research-ops-cleanup:artifact_cleanup:{created_at}".replace(" ", "_"),
                    "artifact_cleanup",
                    "research-ops-cleanup",
                    _dumps({"actor_ref": actor_ref, "deleted": plan.to_json(), "reason": "release-check/demo/test artifact cleanup"}),
                    created_at,
                ),
            )
        return plan


class ResearchOperationsService:
    def __init__(self, repository: SQLiteResearchOperationRepository) -> None:
        self._repository = repository

    def analyze(self, report_id: str, champion: BacktestEvidence, challenger: BacktestEvidence, *, generated_at: str, min_trades: int = 30, slot: str = "default") -> ResearchOperationReport:
        _validate_ref(report_id, "report_id")
        _validate_utc(generated_at)
        quality = research_quality_gate(challenger, min_trades=min_trades)
        confidence = statistical_confidence(challenger, quality)
        dominance = candidate_dominance(champion, challenger, quality)
        period = research_period_policy(challenger, quality)
        recommendation = promotion_recommendation(report_id, champion, challenger, quality, confidence, dominance)
        audit_ref = self._repository.append_audit("analysis_created", recommendation.recommendation_id, {"report_id": report_id, "slot": slot, "quality": quality.status.value}, generated_at)
        report = ResearchOperationReport(report_id, generated_at, champion, challenger, quality, confidence, dominance, period, recommendation, None, False, (audit_ref,))
        self._repository.add_report(report)
        return report

    def approve_and_apply(self, report_id: str, *, actor_ref: str, approved_at: str, slot: str = "default") -> StrategyConfigVersion:
        report = self._require_report(report_id)
        if report.recommendation.decision is not RecommendationDecision.RECOMMEND_CHALLENGER:
            raise ValueError("only challenger recommendations can be applied")
        if not actor_ref:
            raise ValueError("human approval actor is required")
        _validate_utc(approved_at)
        self._repository.add_approval(report.recommendation.recommendation_id, ApprovalStatus.APPROVED, actor_ref=actor_ref, decided_at=approved_at, reason="explicit human approval")
        report_is_artifact = _is_artifact_text(report.report_id, report.recommendation.recommendation_id)
        previous = self._repository.active_config(slot, include_artifacts=report_is_artifact)
        latest = self._repository.latest_config(slot, include_artifacts=True)
        revision = (latest.revision + 1) if latest else 1
        config = StrategyConfigVersion(
            f"strategy-config:{slot}:{revision}",
            slot,
            revision,
            report.challenger.strategy_ref,
            dict(report.recommendation.proposed_config),
            report.recommendation.recommendation_id,
            ApprovalStatus.APPLIED,
            approved_at,
            previous.config_id if previous else None,
            previous.config_id if previous else None,
        )
        self._repository.add_config(config)
        self._repository.add_approval(report.recommendation.recommendation_id, ApprovalStatus.APPLIED, actor_ref=actor_ref, decided_at=approved_at, reason="approved config applied")
        self._repository.append_audit("config_applied", config.config_id, {"report_id": report_id, "previous_config_id": config.previous_config_id, "approval_required": True}, approved_at)
        return config

    def rollback(self, config_id: str, *, actor_ref: str, rolled_back_at: str, slot: str = "default") -> StrategyConfigVersion:
        if not actor_ref:
            raise ValueError("rollback actor is required")
        _validate_utc(rolled_back_at)
        target = self._find_config(config_id)
        active = self._repository.active_config(slot, include_artifacts=_is_artifact_config(target))
        if active is None or active.config_id != config_id:
            raise ValueError("only active config can be rolled back")
        if active.rollback_ref is None:
            raise ValueError("rollback_ref is required")
        previous = self._find_config(active.rollback_ref)
        revision = active.revision + 1
        restored = StrategyConfigVersion(
            f"strategy-config:{slot}:{revision}",
            slot,
            revision,
            previous.strategy_ref,
            dict(previous.parameters),
            active.source_recommendation_id,
            ApprovalStatus.APPLIED,
            rolled_back_at,
            active.config_id,
            active.config_id,
        )
        self._repository.add_config(restored)
        self._repository.append_audit("config_rolled_back", restored.config_id, {"from_config_id": active.config_id, "restored_config_id": previous.config_id, "actor_ref": actor_ref}, rolled_back_at)
        return restored

    def _require_report(self, report_id: str) -> ResearchOperationReport:
        report = self._repository.get_report(report_id)
        if report is None:
            raise KeyError(report_id)
        return report

    def _find_config(self, config_id: str) -> StrategyConfigVersion:
        rows = self._repository._connection.execute("SELECT payload_json FROM strategy_config_versions WHERE config_id = ?", (config_id,)).fetchall()
        if not rows:
            raise KeyError(config_id)
        return config_from_json(str(rows[-1][0]))


def research_quality_gate(evidence: BacktestEvidence, *, min_trades: int) -> ResearchQualityGate:
    reasons: list[str] = []
    if evidence.fixture_backed:
        reasons.append("fixture-backed evidence cannot drive configuration changes")
    if evidence.source != "real":
        reasons.append("non-real evidence cannot drive configuration changes")
    if evidence.blocking_findings:
        reasons.append("blocking data-quality findings present")
    if evidence.trade_count < min_trades:
        reasons.append("insufficient sample: trade count below minimum")
    if evidence.fixture_backed or evidence.source != "real" or evidence.blocking_findings:
        status = QualityStatus.FAIL
    elif evidence.trade_count < min_trades:
        status = QualityStatus.INSUFFICIENT_SAMPLE
    else:
        status = QualityStatus.PASS
    return ResearchQualityGate(status, evidence.trade_count, min_trades, evidence.source, evidence.fixture_backed, tuple(reasons))


def statistical_confidence(evidence: BacktestEvidence, quality: ResearchQualityGate) -> StatisticalConfidence:
    win_rate = _float_or_none(evidence.metrics.get("win_rate"))
    profit_factor = _float_or_none(evidence.metrics.get("profit_factor"))
    mdd = _float_or_none(evidence.metrics.get("mdd"))
    reasons: list[str] = []
    score = min(1.0, evidence.trade_count / max(float(quality.min_trades * 2), 1.0))
    if win_rate is not None:
        score += max(0.0, min(0.2, (win_rate - 0.5) * 0.4))
    if profit_factor is not None and profit_factor >= 1.2:
        score += 0.15
    if mdd is not None and mdd > 0.18:
        score -= 0.2
        reasons.append("drawdown is high")
    if quality.status is QualityStatus.INSUFFICIENT_SAMPLE:
        score = min(score, 0.35)
        reasons.append("insufficient sample caps confidence")
    if quality.status is QualityStatus.FAIL:
        score = 0.0
        reasons.append("quality gate failed")
    score = max(0.0, min(1.0, round(score, 4)))
    level = ConfidenceLevel.HIGH if score >= 0.7 else ConfidenceLevel.MEDIUM if score >= 0.45 else ConfidenceLevel.LOW
    return StatisticalConfidence(level, score, evidence.trade_count, win_rate, profit_factor, mdd, tuple(reasons))


def candidate_dominance(champion: BacktestEvidence, challenger: BacktestEvidence, quality: ResearchQualityGate) -> CandidateDominance:
    if quality.status is not QualityStatus.PASS:
        return CandidateDominance(DominanceDecision.INSUFFICIENT, champion.result_id, challenger.result_id, None, None, None, ("quality gate did not pass",))
    c_return = _float_or_none(champion.metrics.get("total_return"))
    h_return = _float_or_none(challenger.metrics.get("total_return"))
    c_mdd = _float_or_none(champion.metrics.get("mdd"))
    h_mdd = _float_or_none(challenger.metrics.get("mdd"))
    c_pf = _float_or_none(champion.metrics.get("profit_factor"))
    h_pf = _float_or_none(challenger.metrics.get("profit_factor"))
    return_delta = None if c_return is None or h_return is None else h_return - c_return
    mdd_delta = None if c_mdd is None or h_mdd is None else h_mdd - c_mdd
    pf_delta = None if c_pf is None or h_pf is None else h_pf - c_pf
    reasons: list[str] = []
    dominates = True
    if return_delta is None or return_delta < 0.02:
        dominates = False
        reasons.append("return improvement below threshold")
    if mdd_delta is None or mdd_delta > 0.02:
        dominates = False
        reasons.append("drawdown degradation above threshold")
    if pf_delta is None or pf_delta < 0.05:
        dominates = False
        reasons.append("profit factor improvement below threshold")
    return CandidateDominance(DominanceDecision.DOMINATES if dominates else DominanceDecision.MIXED, champion.result_id, challenger.result_id, return_delta, mdd_delta, pf_delta, tuple(reasons))


def research_period_policy(evidence: BacktestEvidence, quality: ResearchQualityGate) -> ResearchPeriodPlan:
    if quality.status is QualityStatus.INSUFFICIENT_SAMPLE:
        start_year = int(evidence.period_start[:4]) - 2
        expanded_start = f"{start_year}{evidence.period_start[4:]}"
        return ResearchPeriodPlan("expand_and_retest", evidence.period_start, evidence.period_end, expanded_start, evidence.period_end, True, "trade count below minimum")
    return ResearchPeriodPlan("current_period_ok", evidence.period_start, evidence.period_end, evidence.period_start, evidence.period_end, False, "sample gate satisfied")


def promotion_recommendation(report_id: str, champion: BacktestEvidence, challenger: BacktestEvidence, quality: ResearchQualityGate, confidence: StatisticalConfidence, dominance: CandidateDominance) -> PromotionRecommendation:
    if quality.status is QualityStatus.INSUFFICIENT_SAMPLE:
        decision = RecommendationDecision.NEEDS_RETEST
        reasons = ("period expansion required before candidate comparison",)
    elif quality.status is QualityStatus.PASS and confidence.level is not ConfidenceLevel.LOW and dominance.decision is DominanceDecision.DOMINATES:
        decision = RecommendationDecision.RECOMMEND_CHALLENGER
        reasons = ("challenger dominates champion under configured thresholds", "human approval required before configuration change")
    else:
        decision = RecommendationDecision.HOLD
        reasons = ("candidate dominance or confidence is insufficient",)
    proposed = {"strategy_ref": challenger.strategy_ref, "source_result_id": challenger.result_id, "mode": "research_config_only", "live_trading": False}
    return PromotionRecommendation(f"research-recommendation:{report_id}", decision, True, champion.result_id, challenger.result_id, proposed, reasons)


def operation_report_markdown(report: ResearchOperationReport) -> str:
    lines = [
        "[연구 운영 보고서]",
        f"- report_id={report.report_id}",
        f"- quality={report.quality_gate.status.value} trade_count={report.quality_gate.trade_count}/{report.quality_gate.min_trades}",
        f"- confidence={report.confidence.level.value} score={report.confidence.score}",
        f"- dominance={report.dominance.decision.value}",
        f"- recommendation={report.recommendation.decision.value}",
        f"- approval_required={str(report.recommendation.approval_required).lower()}",
        f"- period_policy={report.period_plan.status}",
        "- 자동 주문/KIS 주문/Champion 자동 승격은 수행하지 않았습니다.",
    ]
    if report.period_plan.expansion_required:
        lines.append(f"- re_test_period={report.period_plan.expanded_start}~{report.period_plan.expanded_end}")
    if report.config_version:
        lines.append(f"- applied_config={report.config_version.config_id}")
    return "\n".join(lines)


def fixture_evidence_pair(*, sufficient: bool = True) -> tuple[BacktestEvidence, BacktestEvidence]:
    champion = BacktestEvidence("result:champion", "strategy:champion", "2021-01-01", "2026-07-24", "real", False, {"total_return": 0.18, "mdd": 0.12, "profit_factor": 1.22, "trade_count": 42, "win_rate": 0.55}, "pass_with_warnings", 1, 0)
    challenger_trades = 48 if sufficient else 3
    challenger = BacktestEvidence("result:challenger", "strategy:challenger", "2025-01-02" if not sufficient else "2021-01-01", "2026-07-24", "real", False, {"total_return": 0.25, "mdd": 0.10, "profit_factor": 1.36, "trade_count": challenger_trades, "win_rate": 0.58}, "pass_with_warnings", 1, 0)
    return champion, challenger


def report_from_json(value: str) -> ResearchOperationReport:
    payload = json.loads(value)
    champion = _evidence_from_dict(payload["champion"])
    challenger = _evidence_from_dict(payload["challenger"])
    quality = ResearchQualityGate(QualityStatus(payload["quality_gate"]["status"]), int(payload["quality_gate"]["trade_count"]), int(payload["quality_gate"]["min_trades"]), str(payload["quality_gate"]["evidence_source"]), bool(payload["quality_gate"]["fixture_backed"]), tuple(str(item) for item in payload["quality_gate"]["reasons"]))
    confidence = StatisticalConfidence(ConfidenceLevel(payload["confidence"]["level"]), float(payload["confidence"]["score"]), int(payload["confidence"]["trade_count"]), _float_or_none(payload["confidence"].get("win_rate")), _float_or_none(payload["confidence"].get("profit_factor")), _float_or_none(payload["confidence"].get("mdd")), tuple(str(item) for item in payload["confidence"]["reasons"]))
    dominance = CandidateDominance(DominanceDecision(payload["dominance"]["decision"]), str(payload["dominance"]["champion_result_id"]), str(payload["dominance"]["challenger_result_id"]), _float_or_none(payload["dominance"].get("return_delta")), _float_or_none(payload["dominance"].get("mdd_delta")), _float_or_none(payload["dominance"].get("profit_factor_delta")), tuple(str(item) for item in payload["dominance"]["reasons"]))
    period = ResearchPeriodPlan(**payload["period_plan"])
    recommendation = PromotionRecommendation(str(payload["recommendation"]["recommendation_id"]), RecommendationDecision(payload["recommendation"]["decision"]), bool(payload["recommendation"]["approval_required"]), str(payload["recommendation"]["champion_result_id"]), str(payload["recommendation"]["challenger_result_id"]), dict(payload["recommendation"]["proposed_config"]), tuple(str(item) for item in payload["recommendation"]["reasons"]))
    config_payload = payload.get("config_version")
    config = config_from_json(json.dumps(config_payload)) if config_payload else None
    return ResearchOperationReport(str(payload["report_id"]), str(payload["generated_at"]), champion, challenger, quality, confidence, dominance, period, recommendation, config, bool(payload["rollback_available"]), tuple(str(item) for item in payload["audit_refs"]))


def config_from_json(value: str) -> StrategyConfigVersion:
    payload = json.loads(value)
    return StrategyConfigVersion(str(payload["config_id"]), str(payload["slot"]), int(payload["revision"]), str(payload["strategy_ref"]), dict(payload["parameters"]), str(payload["source_recommendation_id"]), ApprovalStatus(payload["status"]), str(payload["created_at"]), payload.get("previous_config_id"), payload.get("rollback_ref"))


def is_research_operation_artifact_ref(value: str) -> bool:
    return _is_artifact_text(value)


def _evidence_from_dict(payload: dict[str, object]) -> BacktestEvidence:
    return BacktestEvidence(str(payload["result_id"]), str(payload["strategy_ref"]), str(payload["period_start"]), str(payload["period_end"]), str(payload["source"]), bool(payload["fixture_backed"]), dict(payload["metrics"]), str(payload["quality_status"]), int(payload.get("provider_gap_count", 0)), int(payload.get("blocking_findings", 0)))


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _validate_ref(value: str, field: str) -> None:
    if REF_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe ref")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must be ISO 8601 UTC")


def _is_artifact_config(config: StrategyConfigVersion) -> bool:
    return _is_artifact_text(config.config_id, config.source_recommendation_id, _dumps(config.to_json()))


def _is_artifact_text(*values: str) -> bool:
    return any(marker in value for marker in ARTIFACT_MARKERS for value in values)


def _artifact_ids(rows: list[sqlite3.Row] | list[tuple[Any, ...]], id_index: int) -> tuple[str, ...]:
    return tuple(str(row[id_index]) for row in rows if _is_artifact_text(*(str(item) for item in row)))


def _delete_ids(connection: sqlite3.Connection, table: str, column: str, ids: tuple[str, ...]) -> None:
    for item_id in ids:
        connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (item_id,))


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
