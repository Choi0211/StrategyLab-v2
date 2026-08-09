from __future__ import annotations

import unittest

from gaon.knowledge.evidence_hypothesis import EvidenceBackedHypothesisGenerator
from gaon.knowledge.external_research_memory import ExternalResearchMemoryRecord
from gaon.knowledge.strategy_experiment import StrategyExperimentBuilder
from gaon.knowledge.validation_loop_v2 import (
    AuthoritativeValidationEvidence,
    AutonomousValidationLoopV2,
    ValidationLoopV2Blocker,
    ValidationLoopV2Status,
    validation_loop_v2_release_check,
)


def _experiment():
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:test-validation",
        fingerprint="a" * 64,
        topic_key="strategy.validation.robustness",
        loop_id="knowledge-research-loop:test-validation",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("add validation gate",),
        rationale="Evidence should gate progression.",
        mechanism="Use authoritative metrics only.",
        falsification_criteria=("Reject if metrics are not authoritative.",),
    )
    return StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id="strategy:baseline",
        baseline_strategy_fingerprint="baseline-fingerprint",
        assumptions_fingerprint="assumptions-fingerprint",
        universe_symbols=("005930", "000660"),
        start="2021-07-25",
        end="2026-07-24",
    )


def _evidence(experiment_id: str, *, trade_count: int = 42, quality: str = "pass"):
    return AuthoritativeValidationEvidence(
        evidence_id="validation-evidence:test",
        experiment_id=experiment_id,
        backtest_result_id="backtest:test",
        source="fixture:validation-loop-v2",
        fixture_backed=True,
        quality_status=quality,
        blocking_findings=(),
        metrics={"trade_count": trade_count, "total_return": 0.12, "mdd": 0.08},
        trade_count=trade_count,
        created_at="2026-08-08T00:00:00+00:00",
    )


class AutonomousValidationLoopV2Tests(unittest.TestCase):
    def test_accepts_authoritative_evidence_for_review_without_execution(self) -> None:
        experiment = _experiment()
        result = AutonomousValidationLoopV2().assess(
            experiment,
            _evidence(experiment.experiment_id),
        )

        self.assertEqual(ValidationLoopV2Status.ACCEPTED_FOR_REVIEW, result.status)
        self.assertEqual("medium", result.confidence)
        self.assertFalse(result.backtest_executed)
        self.assertFalse(result.production_approved)
        self.assertFalse(result.strategy_mutated)

    def test_low_trade_count_needs_more_evidence(self) -> None:
        experiment = _experiment()
        result = AutonomousValidationLoopV2().assess(
            experiment,
            _evidence(experiment.experiment_id, trade_count=3),
        )

        self.assertEqual(ValidationLoopV2Status.NEEDS_MORE_EVIDENCE, result.status)
        self.assertIn("insufficient sample", " ".join(result.warnings))

    def test_experiment_mismatch_is_blocked(self) -> None:
        experiment = _experiment()
        result = AutonomousValidationLoopV2().assess(experiment, _evidence("different"))

        self.assertEqual(ValidationLoopV2Status.BLOCKED, result.status)
        self.assertIn(ValidationLoopV2Blocker.EXPERIMENT_MISMATCH, result.blockers)

    def test_blocking_quality_is_fail_closed(self) -> None:
        experiment = _experiment()
        evidence = AuthoritativeValidationEvidence(
            evidence_id="validation-evidence:block",
            experiment_id=experiment.experiment_id,
            backtest_result_id="backtest:block",
            source="real:yahoo-chart",
            fixture_backed=False,
            quality_status="fail",
            blocking_findings=("invalid_ohlc",),
            metrics={"trade_count": 40},
            trade_count=40,
            created_at="2026-08-08T00:00:00+00:00",
        )
        result = AutonomousValidationLoopV2().assess(experiment, evidence)

        self.assertEqual(ValidationLoopV2Status.BLOCKED, result.status)
        self.assertIn(ValidationLoopV2Blocker.BLOCKING_DATA_QUALITY, result.blockers)

    def test_metric_trade_count_mismatch_is_blocked(self) -> None:
        experiment = _experiment()
        evidence = AuthoritativeValidationEvidence(
            evidence_id="validation-evidence:fabricated",
            experiment_id=experiment.experiment_id,
            backtest_result_id="backtest:fabricated",
            source="real:yahoo-chart",
            fixture_backed=False,
            quality_status="pass",
            blocking_findings=(),
            metrics={"trade_count": 99},
            trade_count=40,
            created_at="2026-08-08T00:00:00+00:00",
        )
        result = AutonomousValidationLoopV2().assess(experiment, evidence)

        self.assertEqual(ValidationLoopV2Status.BLOCKED, result.status)
        self.assertIn(ValidationLoopV2Blocker.FABRICATED_METRIC, result.blockers)

    def test_release_check_passes(self) -> None:
        payload = validation_loop_v2_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual("accepted_for_review", payload["status"])


if __name__ == "__main__":
    unittest.main()
