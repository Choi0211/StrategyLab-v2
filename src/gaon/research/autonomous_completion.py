"""Autonomous research completion contracts for Sprints 156-163.

The module is deterministic and advisory. It does not place orders, promote a
Champion, mutate production strategy configuration, or validate Learning Memory
knowledge without explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

AUTONOMOUS_COMPLETION_SCHEMA_VERSION = 1


class AdequacyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    DEGRADED = "degraded"
    INVALID = "invalid"


class ValidationStopReason(str, Enum):
    NONE = "none"
    DATA_QUALITY_BLOCKING = "data_quality_blocking"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    SYMBOL_COVERAGE_INSUFFICIENT = "symbol_coverage_insufficient"
    PLAN_REQUIRED = "plan_required"


class ValidationNeedKind(str, Enum):
    EXTEND_PERIOD = "extend_period"
    TEST_OTHER_MARKET_REGIME = "test_other_market_regime"
    MULTI_SYMBOL_VALIDATION = "multi_symbol_validation"
    PARAMETER_ROBUSTNESS = "parameter_robustness"
    OUT_OF_SAMPLE = "out_of_sample"


@dataclass(frozen=True)
class EvidenceAdequacy:
    trade_count: int
    observation_days: int
    market_regime_count: int
    mdd: float | None
    wins: int
    losses: int
    data_quality_status: str
    missing_bar_count: int
    zero_volume_bar_count: int
    symbol_count: int
    eligible_symbol_count: int

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "trade_count": self.trade_count,
            "observation_days": self.observation_days,
            "market_regime_count": self.market_regime_count,
            "mdd": self.mdd,
            "wins": self.wins,
            "losses": self.losses,
            "data_quality_status": self.data_quality_status,
            "missing_bar_count": self.missing_bar_count,
            "zero_volume_bar_count": self.zero_volume_bar_count,
            "symbol_count": self.symbol_count,
            "eligible_symbol_count": self.eligible_symbol_count,
        }


@dataclass(frozen=True)
class ValidationNeed:
    kind: ValidationNeedKind
    reason: str
    priority: int
    required_before_decision: bool

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "priority": self.priority,
            "required_before_decision": self.required_before_decision,
        }


@dataclass(frozen=True)
class ValidationPlan:
    needs: tuple[ValidationNeed, ...]
    stop_reason: ValidationStopReason
    bounded: bool
    can_change_strategy: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "needs": [need.to_json() for need in self.needs],
            "stop_reason": self.stop_reason.value,
            "bounded": self.bounded,
            "can_change_strategy": self.can_change_strategy,
        }


@dataclass(frozen=True)
class ResearchAdequacyAssessment:
    status: AdequacyStatus
    adequacy: EvidenceAdequacy
    plan: ValidationPlan
    warnings: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "status": self.status.value,
            "adequacy": self.adequacy.to_json(),
            "plan": self.plan.to_json(),
            "warnings": list(self.warnings),
            "evidence_refs": list(self.evidence_refs),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


class AdaptiveResearchValidator:
    """Classify evidence adequacy and propose validation needs only."""

    def __init__(self, *, min_trades: int = 30, min_observation_days: int = 180, min_regimes: int = 2) -> None:
        self._min_trades = min_trades
        self._min_observation_days = min_observation_days
        self._min_regimes = min_regimes

    def assess(self, payload: dict[str, object]) -> ResearchAdequacyAssessment:
        adequacy = _adequacy_from_payload(payload)
        needs: list[ValidationNeed] = []
        warnings: list[str] = []
        stop_reason = ValidationStopReason.NONE

        blocking_quality = str(adequacy.data_quality_status).casefold() in {"fail", "invalid"} or adequacy.missing_bar_count > 0 or adequacy.zero_volume_bar_count > 0
        if blocking_quality:
            needs.append(ValidationNeed(ValidationNeedKind.OUT_OF_SAMPLE, "data quality must be repaired or independently verified before conclusions", 0, True))
            warnings.append("blocking data quality prevents a research decision")
            status = AdequacyStatus.INVALID
            stop_reason = ValidationStopReason.DATA_QUALITY_BLOCKING
        else:
            if adequacy.trade_count < self._min_trades:
                needs.append(ValidationNeed(ValidationNeedKind.EXTEND_PERIOD, "trade count is below the minimum statistical sample", 1, True))
                warnings.append("insufficient trade sample")
            if adequacy.observation_days < self._min_observation_days:
                needs.append(ValidationNeed(ValidationNeedKind.EXTEND_PERIOD, "observation period is too short", 2, True))
            if adequacy.market_regime_count < self._min_regimes:
                needs.append(ValidationNeed(ValidationNeedKind.TEST_OTHER_MARKET_REGIME, "market regime coverage is incomplete", 3, True))
            if adequacy.symbol_count > 0 and adequacy.eligible_symbol_count < adequacy.symbol_count:
                needs.append(ValidationNeed(ValidationNeedKind.MULTI_SYMBOL_VALIDATION, "some symbols were not eligible for evidence aggregation", 4, True))
            if adequacy.wins + adequacy.losses < self._min_trades:
                needs.append(ValidationNeed(ValidationNeedKind.PARAMETER_ROBUSTNESS, "win/loss sample is too small for parameter confidence", 5, False))
            if needs:
                status = AdequacyStatus.INSUFFICIENT if adequacy.trade_count < self._min_trades else AdequacyStatus.DEGRADED
                stop_reason = ValidationStopReason.INSUFFICIENT_SAMPLE if adequacy.trade_count < self._min_trades else ValidationStopReason.PLAN_REQUIRED
            else:
                status = AdequacyStatus.SUFFICIENT

        return ResearchAdequacyAssessment(
            status=status,
            adequacy=adequacy,
            plan=ValidationPlan(tuple(sorted(needs, key=lambda item: item.priority)), stop_reason, bounded=True),
            warnings=tuple(warnings),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ()) if item),
        )


def gaon_adaptive_validation_release_check() -> dict[str, object]:
    payload = {
        "metrics": {"trade_count": 1, "mdd": 0.04, "wins": 1, "losses": 0},
        "observation_days": 128,
        "market_regime_count": 1,
        "quality": {"status": "pass", "missing_bar_count": 0, "zero_volume_bar_count": 0},
        "symbol_coverage": {"symbol_count": 1, "eligible_symbol_count": 1},
        "evidence_refs": ("release-check:backtest",),
    }
    assessment = AdaptiveResearchValidator().assess(payload)
    if assessment.status is not AdequacyStatus.INSUFFICIENT:
        raise ValueError("adaptive validation did not detect insufficient evidence")
    kinds = {need.kind for need in assessment.plan.needs}
    required = {ValidationNeedKind.EXTEND_PERIOD, ValidationNeedKind.TEST_OTHER_MARKET_REGIME, ValidationNeedKind.PARAMETER_ROBUSTNESS}
    if not required.issubset(kinds):
        raise ValueError("adaptive validation missed required validation needs")
    if assessment.plan.can_change_strategy:
        raise ValueError("adaptive validation must not authorize strategy changes")
    invalid = AdaptiveResearchValidator().assess({**payload, "quality": {"status": "fail", "missing_bar_count": 1, "zero_volume_bar_count": 0}})
    if invalid.status is not AdequacyStatus.INVALID or invalid.plan.stop_reason is not ValidationStopReason.DATA_QUALITY_BLOCKING:
        raise ValueError("adaptive validation did not fail closed on data quality")
    return {"assessment": assessment.to_json(), "invalid_status": invalid.status.value, "safety": "pass"}


def _adequacy_from_payload(payload: dict[str, object]) -> EvidenceAdequacy:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    coverage = payload.get("symbol_coverage") if isinstance(payload.get("symbol_coverage"), dict) else {}
    return EvidenceAdequacy(
        trade_count=_int(metrics.get("trade_count")),
        observation_days=_int(payload.get("observation_days")),
        market_regime_count=_int(payload.get("market_regime_count")),
        mdd=_float_or_none(metrics.get("mdd")),
        wins=_int(metrics.get("wins")),
        losses=_int(metrics.get("losses")),
        data_quality_status=str(quality.get("status", "unknown")),
        missing_bar_count=_int(quality.get("missing_bar_count")),
        zero_volume_bar_count=_int(quality.get("zero_volume_bar_count")),
        symbol_count=_int(coverage.get("symbol_count", 1)),
        eligible_symbol_count=_int(coverage.get("eligible_symbol_count", 1)),
    )


def _int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
