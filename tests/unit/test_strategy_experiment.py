from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.knowledge.evidence_hypothesis import (
    EvidenceBackedHypothesisGenerator,
)
from gaon.knowledge.external_research_memory import ExternalResearchMemoryRecord
from gaon.knowledge.strategy_experiment import (
    StrategyExperimentBlocker,
    StrategyExperimentBuilder,
    StrategyExperimentStatus,
    strategy_experiment_builder_release_check,
)


def _hypothesis():
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:test",
        fingerprint="e" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:test",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a", "claim:b"),
        question_ids=("research-question:a",),
        source_ids=("source:a", "source:b"),
        created_at="2026-08-08T00:00:00+00:00",
    )
    return EvidenceBackedHypothesisGenerator().generate(
        topic_key="strategy.breakout.robustness",
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="Evidence suggests regime context matters.",
        mechanism="Filter entries before breakout execution.",
        falsification_criteria=("Reject if validation evidence does not improve robustness.",),
    )


class StrategyExperimentBuilderTests(unittest.TestCase):
    def test_proposed_hypothesis_builds_validation_ready_experiment(self) -> None:
        experiment = StrategyExperimentBuilder().build(
            hypothesis=_hypothesis(),
            baseline_strategy_id="strategy:baseline",
            baseline_strategy_fingerprint="baseline-fingerprint",
            assumptions_fingerprint="assumptions-fingerprint",
            universe_symbols=("005930", "000660"),
            start="2021-07-25",
            end="2026-07-24",
        )

        self.assertEqual(
            StrategyExperimentStatus.READY_FOR_VALIDATION,
            experiment.status,
        )
        self.assertEqual(("000660", "005930"), experiment.universe_symbols)
        self.assertFalse(experiment.backtest_executed)
        self.assertFalse(experiment.tested)
        self.assertFalse(experiment.production_approved)
        self.assertFalse(experiment.strategy_mutated)

    def test_fingerprint_is_stable_for_symbol_order(self) -> None:
        builder = StrategyExperimentBuilder()
        kwargs = {
            "hypothesis": _hypothesis(),
            "baseline_strategy_id": "strategy:baseline",
            "baseline_strategy_fingerprint": "baseline-fingerprint",
            "assumptions_fingerprint": "assumptions-fingerprint",
            "start": "2021-07-25",
            "end": "2026-07-24",
        }

        first = builder.build(universe_symbols=("005930", "000660"), **kwargs)
        second = builder.build(universe_symbols=("000660", "005930"), **kwargs)

        self.assertEqual(first.experiment_id, second.experiment_id)

    def test_tested_hypothesis_is_blocked(self) -> None:
        hypothesis = replace(_hypothesis(), tested=True)

        experiment = StrategyExperimentBuilder().build(
            hypothesis=hypothesis,
            baseline_strategy_id="strategy:baseline",
            baseline_strategy_fingerprint="baseline-fingerprint",
            assumptions_fingerprint="assumptions-fingerprint",
            universe_symbols=("005930",),
            start="2021-07-25",
            end="2026-07-24",
        )

        self.assertEqual(StrategyExperimentStatus.BLOCKED, experiment.status)
        self.assertIn(
            StrategyExperimentBlocker.HYPOTHESIS_ALREADY_TESTED,
            experiment.blockers,
        )

    def test_invalid_period_and_missing_universe_are_blocked(self) -> None:
        experiment = StrategyExperimentBuilder().build(
            hypothesis=_hypothesis(),
            baseline_strategy_id="strategy:baseline",
            baseline_strategy_fingerprint="baseline-fingerprint",
            assumptions_fingerprint="assumptions-fingerprint",
            universe_symbols=(),
            start="2026-07-24",
            end="2021-07-25",
        )

        self.assertEqual(StrategyExperimentStatus.BLOCKED, experiment.status)
        self.assertIn(StrategyExperimentBlocker.MISSING_UNIVERSE, experiment.blockers)
        self.assertIn(StrategyExperimentBlocker.INVALID_PERIOD, experiment.blockers)

    def test_release_check_passes(self) -> None:
        payload = strategy_experiment_builder_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual("ready_for_validation", payload["status"])


if __name__ == "__main__":
    unittest.main()
