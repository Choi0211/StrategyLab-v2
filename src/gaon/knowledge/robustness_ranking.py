"""Sprint 183 - Strategy Robustness Ranking.

Ranks validated experiment evidence without promoting or mutating strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .validation_loop_v2 import (
    AuthoritativeValidationEvidence,
    ValidationLoopV2Result,
    ValidationLoopV2Status,
    validation_loop_v2_release_check,
)


ROBUSTNESS_RANKING_SCHEMA_VERSION = 1


class RobustnessRankingStatus(str, Enum):
    RANKED = "ranked"
    BLOCKED = "blocked"


class RobustnessRankingBlocker(str, Enum):
    NO_VALIDATED_EVIDENCE = "no_validated_evidence"
    MISSING_REQUIRED_METRICS = "missing_required_metrics"
    BLOCKING_VALIDATION_STATUS = "blocking_validation_status"


@dataclass(frozen=True)
class RobustnessRankedStrategy:
    rank: int
    experiment_id: str
    evidence_id: str
    score: float
    trade_count: int
    total_return: float
    mdd: float
    profit_factor: float
    win_rate: float
    source: str
    fixture_backed: bool
    eligible_for_review: bool = True
    promotion_recommended: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": ROBUSTNESS_RANKING_SCHEMA_VERSION,
            "rank": self.rank,
            "experiment_id": self.experiment_id,
            "evidence_id": self.evidence_id,
            "score": self.score,
            "trade_count": self.trade_count,
            "total_return": self.total_return,
            "mdd": self.mdd,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "eligible_for_review": self.eligible_for_review,
            "promotion_recommended": self.promotion_recommended,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


@dataclass(frozen=True)
class RobustnessRankingResult:
    status: RobustnessRankingStatus
    blockers: tuple[RobustnessRankingBlocker, ...]
    ranked: tuple[RobustnessRankedStrategy, ...]
    warnings: tuple[str, ...]
    automatic_champion_promotion: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": ROBUSTNESS_RANKING_SCHEMA_VERSION,
            "status": self.status.value,
            "blockers": [item.value for item in self.blockers],
            "ranked": [item.to_json() for item in self.ranked],
            "warnings": list(self.warnings),
            "automatic_champion_promotion": self.automatic_champion_promotion,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class StrategyRobustnessRanker:
    required_metrics = ("total_return", "mdd", "profit_factor", "win_rate")

    def rank(self, results: tuple[ValidationLoopV2Result, ...]) -> RobustnessRankingResult:
        blockers: list[RobustnessRankingBlocker] = []
        warnings: list[str] = []
        accepted = [
            result for result in results
            if result.status is ValidationLoopV2Status.ACCEPTED_FOR_REVIEW and result.evidence is not None
        ]
        if len(accepted) != len(results):
            blockers.append(RobustnessRankingBlocker.BLOCKING_VALIDATION_STATUS)
        if not accepted:
            blockers.append(RobustnessRankingBlocker.NO_VALIDATED_EVIDENCE)

        missing_metric = any(
            not self._has_required_metrics(result.evidence)
            for result in accepted
        )
        if missing_metric:
            blockers.append(RobustnessRankingBlocker.MISSING_REQUIRED_METRICS)

        if blockers:
            return RobustnessRankingResult(
                status=RobustnessRankingStatus.BLOCKED,
                blockers=tuple(dict.fromkeys(blockers)),
                ranked=(),
                warnings=tuple(warnings),
            )

        ranked = tuple(
            self._ranked_strategy(index + 1, result.evidence)
            for index, result in enumerate(
                sorted(accepted, key=lambda item: self._score(item.evidence), reverse=True)
            )
        )
        if any(item.fixture_backed for item in ranked):
            warnings.append("fixture-backed rankings are not production approval")
        return RobustnessRankingResult(
            status=RobustnessRankingStatus.RANKED,
            blockers=(),
            ranked=ranked,
            warnings=tuple(warnings),
        )

    @classmethod
    def _has_required_metrics(cls, evidence: AuthoritativeValidationEvidence | None) -> bool:
        return evidence is not None and all(key in evidence.metrics for key in cls.required_metrics)

    @staticmethod
    def _metric(evidence: AuthoritativeValidationEvidence, key: str) -> float:
        return float(evidence.metrics[key])

    def _score(self, evidence: AuthoritativeValidationEvidence | None) -> float:
        if evidence is None:
            return -1.0
        total_return = self._metric(evidence, "total_return")
        mdd = max(self._metric(evidence, "mdd"), 0.001)
        profit_factor = min(self._metric(evidence, "profit_factor"), 5.0)
        win_rate = self._metric(evidence, "win_rate")
        sample = min(evidence.trade_count / 60.0, 1.0)
        return round((total_return / mdd) + profit_factor + win_rate + sample, 6)

    def _ranked_strategy(
        self,
        rank: int,
        evidence: AuthoritativeValidationEvidence | None,
    ) -> RobustnessRankedStrategy:
        if evidence is None:
            raise ValueError("evidence is required")
        return RobustnessRankedStrategy(
            rank=rank,
            experiment_id=evidence.experiment_id,
            evidence_id=evidence.evidence_id,
            score=self._score(evidence),
            trade_count=evidence.trade_count,
            total_return=self._metric(evidence, "total_return"),
            mdd=self._metric(evidence, "mdd"),
            profit_factor=self._metric(evidence, "profit_factor"),
            win_rate=self._metric(evidence, "win_rate"),
            source=evidence.source,
            fixture_backed=evidence.fixture_backed,
        )


def robustness_ranking_release_check() -> Mapping[str, object]:
    validation_payload = validation_loop_v2_release_check()
    from .strategy_experiment import StrategyExperimentBuilder
    from .evidence_hypothesis import EvidenceBackedHypothesisGenerator
    from .external_research_memory import ExternalResearchMemoryRecord
    from .validation_loop_v2 import AutonomousValidationLoopV2

    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:ranking-release",
        fingerprint="b" * 64,
        topic_key="strategy.ranking.robustness",
        loop_id="knowledge-research-loop:ranking-release",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("prefer lower drawdown confirmation",),
        rationale="Drawdown-adjusted performance matters.",
        mechanism="Rank candidates by structured evidence.",
        falsification_criteria=("Reject if ranking metrics are missing.",),
    )
    experiment = StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id="strategy:baseline",
        baseline_strategy_fingerprint="baseline-fingerprint",
        assumptions_fingerprint="assumptions-fingerprint",
        universe_symbols=("005930",),
        start="2021-07-25",
        end="2026-07-24",
    )
    evidence_a = AuthoritativeValidationEvidence(
        evidence_id="validation-evidence:rank-a",
        experiment_id=experiment.experiment_id,
        backtest_result_id="backtest:rank-a",
        source="fixture:robustness-ranking",
        fixture_backed=True,
        quality_status="pass",
        blocking_findings=(),
        metrics={"trade_count": 60, "total_return": 0.18, "mdd": 0.09, "profit_factor": 1.6, "win_rate": 0.56},
        trade_count=60,
        created_at="2026-08-08T00:00:00+00:00",
    )
    evidence_b = AuthoritativeValidationEvidence(
        evidence_id="validation-evidence:rank-b",
        experiment_id=experiment.experiment_id,
        backtest_result_id="backtest:rank-b",
        source="fixture:robustness-ranking",
        fixture_backed=True,
        quality_status="pass",
        blocking_findings=(),
        metrics={"trade_count": 45, "total_return": 0.10, "mdd": 0.12, "profit_factor": 1.2, "win_rate": 0.51},
        trade_count=45,
        created_at="2026-08-08T00:00:00+00:00",
    )
    loop = AutonomousValidationLoopV2()
    ranking = StrategyRobustnessRanker().rank(
        (
            loop.assess(experiment, evidence_b),
            loop.assess(experiment, evidence_a),
        )
    )
    blocked = StrategyRobustnessRanker().rank((loop.assess(experiment, None),))
    checks = {
        "validation_ready": validation_payload["status"] == "accepted_for_review",
        "ranked": ranking.status is RobustnessRankingStatus.RANKED,
        "top": ranking.ranked[0].evidence_id == "validation-evidence:rank-a",
        "blocked": blocked.status is RobustnessRankingStatus.BLOCKED,
        "no_promotion": not ranking.automatic_champion_promotion,
        "no_mutation": not ranking.strategy_mutated and not ranking.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"robustness ranking release check failed: {failed}")
    return {
        "schema_version": ROBUSTNESS_RANKING_SCHEMA_VERSION,
        "status": ranking.status.value,
        "ranked": len(ranking.ranked),
        "top_evidence_id": ranking.ranked[0].evidence_id,
        "checks": checks,
        "safety": "pass",
    }
