from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.knowledge.autonomous_learning_e2e import autonomous_learning_e2e_release_check
from gaon.knowledge.telegram_autonomous_learning import (
    production_autonomous_learning_execution_release_check,
    production_autonomous_learning_payload_from_baseline,
    telegram_autonomous_learning_payload,
)
from gaon.research.krx_real_pipeline import MarketDataAvailability
from gaon.runtime.storage import RuntimeStateStore
from tests.fixtures.knowledge_pipeline import build_experiment, build_real_backtest


class AutonomousLearningE2EReleaseCheckTests(unittest.TestCase):
    def test_release_check_reaches_human_approval_required(self) -> None:
        payload = autonomous_learning_e2e_release_check()

        self.assertEqual("proposed", payload["hypothesis_status"])
        self.assertEqual("accepted_for_review", payload["validation_status"])
        self.assertEqual("ranked", payload["ranking_status"])
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
        self.assertEqual("pass", payload["safety"])

    def test_telegram_wrapper_blocks_fixture_release_evidence_in_production(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            payload = telegram_autonomous_learning_payload(
                store._connection,
                "삼성전자 전략을 처음부터 다시 연구해줘",
                symbol="005930",
            )

            self.assertEqual("autonomous_learning_research", payload["tool"])
            self.assertEqual("005930", payload["symbol"])
            self.assertEqual("autonomous_learning_v2", payload["selected_orchestration"])
            self.assertEqual("blocked_fixture", payload["promotion_status"])
            self.assertEqual("not_requested", payload["human_gate_status"])
            self.assertFalse(payload["approval_required"])
            self.assertTrue(payload["fixture_promotion_blocked"])
            self.assertFalse(payload["production_uses_release_fixture"])
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])
            self.assertFalse(payload["broker_order_called"])
            self.assertFalse(payload["kis_order_called"])
            self.assertIn("baseline", payload)
        finally:
            store.close()

    def test_production_wrapper_does_not_call_release_check_or_fixture_helpers(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            with patch(
                "gaon.knowledge.autonomous_learning_e2e.autonomous_learning_e2e_release_check",
                side_effect=AssertionError("release fixture called"),
            ):
                with patch(
                    "gaon.knowledge.experiment_execution._fixture_experiment_and_backtest",
                    side_effect=AssertionError("fixture backtest helper called"),
                ):
                    payload = telegram_autonomous_learning_payload(store._connection, "삼성전자 전략 연구해줘", symbol="005930")
            self.assertFalse(payload["production_uses_release_fixture"])
            self.assertNotEqual("requires_human_approval", payload["promotion_status"])
        finally:
            store.close()

    def test_real_baseline_with_fixture_candidate_evidence_is_blocked(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False)

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        self.assertEqual("blocked_fixture", result["promotion_status"])
        self.assertFalse(result["approval_required"])
        self.assertTrue(result["fixture_promotion_blocked"])

    def test_real_candidate_backtest_fingerprint_must_match_experiment_candidate(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False)
        payload["candidates"][0]["strategy"]["fingerprint"] = "different"

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        self.assertFalse(result["candidate_strategy_fingerprint_matched"])
        self.assertNotEqual("requires_human_approval", result["promotion_status"])

    def test_real_changed_strategy_uses_candidate_backtest_not_baseline_backtest(self) -> None:
        experiment = build_experiment()
        candidate_backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL, trade_count=60)
        payload = _baseline_payload(experiment, candidate_backtest, baseline_fixture=False)

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        learning = result["autonomous_learning_v2"]
        evidence = learning["promotion_candidate_context"]["authoritative_validation_evidence"]
        self.assertEqual(candidate_backtest.result_id, evidence["backtest_result_id"])
        self.assertTrue(result["candidate_backtest_authoritative"])
        self.assertTrue(result["candidate_strategy_fingerprint_matched"])
        self.assertEqual("requires_human_approval", result["promotion_status"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])

    def test_unimplemented_changed_rule_does_not_fabricate_backtest(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False, changed_fields=())

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        blockers = result["autonomous_learning_v2"]["blockers"]
        self.assertIn("hypothesis_unexecutable", blockers)
        self.assertNotEqual("requires_human_approval", result["promotion_status"])

    def test_production_autonomous_learning_execution_release_check_passes(self) -> None:
        payload = production_autonomous_learning_execution_release_check()

        self.assertFalse(payload["production_uses_release_fixture"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertTrue(payload["candidate_backtest_authoritative"])
        self.assertTrue(payload["candidate_strategy_fingerprint_matched"])
        self.assertTrue(payload["real_data_required"])
        self.assertEqual("pass", payload["safety"])


def _baseline_payload(experiment, candidate_backtest, *, baseline_fixture: bool, changed_fields=("entry.breakout_lookback",)) -> dict[str, object]:
    strategy = candidate_backtest.strategy.to_json()
    source = "fixture" if baseline_fixture else "real"
    baseline_backtest = candidate_backtest.to_json()
    baseline_backtest["source"] = source
    candidate_result = candidate_backtest.to_json()
    return {
        "schema_version": 1,
        "report_id": "krx-real-research-report:test",
        "run_id": "krx-real-research:test",
        "dataset": {
            "metadata": {
                "source": "fixture:krx-real-research" if baseline_fixture else "real:yahoo-chart",
                "fixture_backed": baseline_fixture,
                "start_date": experiment.start,
                "end_date": experiment.end,
                "rows": 1200,
            }
        },
        "quality": {"status": "pass", "findings": []},
        "strategy": {"spec_id": "strategy:baseline", "fingerprint": experiment.baseline_strategy_fingerprint},
        "assumptions": candidate_backtest.assumptions.to_json(),
        "backtest": baseline_backtest,
        "candidates": [
            {
                "candidate_id": "candidate:test",
                "parent_strategy_id": "strategy:baseline",
                "strategy": strategy,
                "changed_fields": list(changed_fields),
                "reason_ko": "verified candidate",
                "provenance": "research_candidate",
                "backtest_result": candidate_result,
            }
        ],
    }


def _external_ready() -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": "evidence_sufficient",
        "question_id": "research-question:test",
        "discovery_run": {
            "results": [
                {
                    "result_id": "discovery:test",
                    "title": "Real provider metadata",
                    "source_type": "research_report",
                    "locator": "https://doi.org/10.0000/example",
                }
            ]
        },
        "normalized_records": [],
        "candidates": [{"candidate_id": "claim:test", "source_id": "source:test"}],
        "blockers": [],
        "network_executed": False,
    }


if __name__ == "__main__":
    unittest.main()
