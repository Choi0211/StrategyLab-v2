from __future__ import annotations

import unittest

from gaon.knowledge.evidence_hypothesis import EvidenceBackedHypothesisGenerator
from gaon.knowledge.external_research_memory import ExternalResearchMemoryRecord
from gaon.knowledge.robustness_ranking import (
    RobustnessRankingBlocker,
    RobustnessRankingStatus,
    StrategyRobustnessRanker,
    robustness_ranking_release_check,
)
from gaon.knowledge.strategy_experiment import StrategyExperimentBuilder
from gaon.knowledge.validation_loop_v2 import (
    AuthoritativeValidationEvidence,
    AutonomousValidationLoopV2,
)


def _experiment():
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:test-ranking",
        fingerprint="c" * 64,
        topic_key="strategy.ranking.robustness",
        loop_id="knowledge-research-loop:test-ranking",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("rank by robustness",),
        rationale="Structured metrics support comparison.",
        mechanism="Use evidence-only scoring.",
        falsification_criteria=("Reject if metrics are missing.",),
    )
    return StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id="strategy:baseline",
        baseline_strategy_fingerprint="baseline-fingerprint",
        assumptions_fingerprint="assumptions-fingerprint",
        universe_symbols=("005930",),
        start="2021-07-25",
        end="2026-07-24",
    )


def _result(experiment, evidence_id: str, *, total_return: float, mdd: float):
    evidence = AuthoritativeValidationEvidence(
        evidence_id=evidence_id,
        experiment_id=experiment.experiment_id,
        backtest_result_id=f"backtest:{evidence_id}",
        source="fixture:robustness-ranking",
        fixture_backed=True,
        quality_status="pass",
        blocking_findings=(),
        metrics={"trade_count": 60, "total_return": total_return, "mdd": mdd, "profit_factor": 1.5, "win_rate": 0.55},
        trade_count=60,
        created_at="2026-08-08T00:00:00+00:00",
    )
    return AutonomousValidationLoopV2().assess(experiment, evidence)


class StrategyRobustnessRankingTests(unittest.TestCase):
    def test_ranks_accepted_evidence_by_structured_metrics(self) -> None:
        experiment = _experiment()
        ranking = StrategyRobustnessRanker().rank(
            (
                _result(experiment, "validation-evidence:weaker", total_return=0.10, mdd=0.15),
                _result(experiment, "validation-evidence:stronger", total_return=0.20, mdd=0.08),
            )
        )

        self.assertEqual(RobustnessRankingStatus.RANKED, ranking.status)
        self.assertEqual("validation-evidence:stronger", ranking.ranked[0].evidence_id)
        self.assertFalse(ranking.automatic_champion_promotion)
        self.assertFalse(ranking.production_approved)
        self.assertFalse(ranking.strategy_mutated)

    def test_missing_required_metrics_blocks_ranking(self) -> None:
        experiment = _experiment()
        evidence = AuthoritativeValidationEvidence(
            evidence_id="validation-evidence:missing",
            experiment_id=experiment.experiment_id,
            backtest_result_id="backtest:missing",
            source="fixture:robustness-ranking",
            fixture_backed=True,
            quality_status="pass",
            blocking_findings=(),
            metrics={"trade_count": 60, "total_return": 0.2},
            trade_count=60,
            created_at="2026-08-08T00:00:00+00:00",
        )
        validation = AutonomousValidationLoopV2().assess(experiment, evidence)
        ranking = StrategyRobustnessRanker().rank((validation,))

        self.assertEqual(RobustnessRankingStatus.BLOCKED, ranking.status)
        self.assertIn(RobustnessRankingBlocker.MISSING_REQUIRED_METRICS, ranking.blockers)

    def test_non_accepted_validation_blocks_ranking(self) -> None:
        experiment = _experiment()
        ranking = StrategyRobustnessRanker().rank(
            (AutonomousValidationLoopV2().assess(experiment, None),)
        )

        self.assertEqual(RobustnessRankingStatus.BLOCKED, ranking.status)
        self.assertIn(RobustnessRankingBlocker.NO_VALIDATED_EVIDENCE, ranking.blockers)

    def test_release_check_passes(self) -> None:
        payload = robustness_ranking_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual("ranked", payload["status"])
        self.assertEqual("validation-evidence:rank-a", payload["top_evidence_id"])


if __name__ == "__main__":
    unittest.main()
