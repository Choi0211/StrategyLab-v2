from __future__ import annotations

import math
import unittest
from dataclasses import replace

from gaon.knowledge.experiment_execution import (
    AuthoritativeExperimentExecutor,
    TrustedValidationEvidenceAdapter,
    authoritative_experiment_execution_release_check,
)
from gaon.knowledge.robustness_ranking import RobustnessRankingStatus
from gaon.knowledge.validation_loop_v2 import ValidationLoopV2Status
from gaon.research.krx_real_pipeline import FieldProvenance, ProvenancedValue, default_execution_assumptions
from tests.fixtures.knowledge_pipeline import build_experiment, build_real_backtest


class TrustedValidationEvidenceAdapterTests(unittest.TestCase):
    def test_rejects_untrusted_evidence_source(self) -> None:
        adapter = TrustedValidationEvidenceAdapter()
        with self.assertRaises(TypeError):
            adapter.from_authoritative_source(build_experiment(), object())  # type: ignore[arg-type]

    def test_maps_actual_structured_backtest_metrics(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, trade_count=60)

        evidence = TrustedValidationEvidenceAdapter().from_real_backtest(experiment, backtest)

        self.assertEqual(backtest.result_id, evidence.backtest_result_id)
        self.assertEqual(60, evidence.trade_count)
        self.assertEqual(0.18, evidence.metrics["total_return"])
        self.assertFalse(evidence.strategy_mutated)
        self.assertFalse(evidence.order_executed)

    def test_assumption_mismatch_is_blocked_before_validation(self) -> None:
        altered_assumptions = replace(
            default_execution_assumptions(),
            initial_capital=ProvenancedValue(2_000_000.0, FieldProvenance.DEFAULT),
        )
        experiment = build_experiment(assumptions=altered_assumptions)
        backtest = build_real_backtest(build_experiment())

        with self.assertRaises(ValueError):
            TrustedValidationEvidenceAdapter().from_real_backtest(experiment, backtest)

    def test_real_profit_factor_infinity_is_not_fabricated(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, trade_count=60, profit_factor=math.inf)

        result = AuthoritativeExperimentExecutor().execute(experiment, backtest)

        self.assertEqual(ValidationLoopV2Status.ACCEPTED_FOR_REVIEW, result.validation.status)
        self.assertEqual(RobustnessRankingStatus.RANKED, result.ranking.status)

    def test_insufficient_sample_stays_needs_more_evidence(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, trade_count=3)

        result = AuthoritativeExperimentExecutor().execute(experiment, backtest)

        self.assertEqual(ValidationLoopV2Status.NEEDS_MORE_EVIDENCE, result.validation.status)
        self.assertNotEqual(RobustnessRankingStatus.RANKED, result.ranking.status)

    def test_release_check_passes(self) -> None:
        payload = authoritative_experiment_execution_release_check()

        self.assertEqual("accepted_for_review", payload["status"])
        self.assertEqual("ranked", payload["ranking_status"])
        self.assertEqual("pass", payload["safety"])


if __name__ == "__main__":
    unittest.main()
