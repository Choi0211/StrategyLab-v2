import unittest
from unittest.mock import patch
import sqlite3

from gaon.runtime.research_grounding import format_grounded_tool_response
from gaon.knowledge.autonomous_quant_partner import (
    autonomous_quant_partner_payload,
    production_authoritative_source_acquisition_release_check,
    production_autonomous_quant_partner_acceptance_release_check,
    production_counter_evidence_release_check,
    production_iterative_research_loop_release_check,
    production_learning_memory_closed_loop_release_check,
    production_promotion_readiness_release_check,
    production_provider_registry_release_check,
    production_research_observability_release_check,
    production_robust_strategy_validation_release_check,
    production_source_diversification_planner_release_check,
    production_strategy_tournament_release_check,
    production_validation_sufficiency_v2_release_check,
)
from gaon.knowledge.telegram_autonomous_learning import (
    production_autonomous_learning_payload_from_baseline,
    production_autonomous_research_wiring_release_check,
    telegram_autonomous_learning_payload,
)


class AutonomousQuantPartnerTests(unittest.TestCase):
    def test_release_checks_pass(self) -> None:
        checks = (
            production_provider_registry_release_check,
            production_authoritative_source_acquisition_release_check,
            production_source_diversification_planner_release_check,
            production_counter_evidence_release_check,
            production_validation_sufficiency_v2_release_check,
            production_iterative_research_loop_release_check,
            production_robust_strategy_validation_release_check,
            production_strategy_tournament_release_check,
            production_learning_memory_closed_loop_release_check,
            production_promotion_readiness_release_check,
            production_research_observability_release_check,
            production_autonomous_quant_partner_acceptance_release_check,
        )
        for check in checks:
            with self.subTest(check=check.__name__):
                payload = check()
                self.assertEqual(payload["safety"], "pass")
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])

    def test_insufficient_sample_plans_more_research_without_approval(self) -> None:
        payload = autonomous_quant_partner_payload(
            "삼성전자 전략을 더 연구해줘",
            symbol="005930",
            baseline=_baseline(trades=7, symbols=1),
            allow_release_fixture=True,
        )
        self.assertEqual(payload["validation_sufficiency_v2"]["status"], "insufficient_sample")
        self.assertFalse(payload["approval_required"])
        self.assertIn("검증 부족", payload["telegram_progress"])

    def test_sufficient_real_evidence_stops_at_human_approval_boundary(self) -> None:
        payload = autonomous_quant_partner_payload(
            "승격 승인 전까지 연구해줘",
            symbol="005930",
            baseline=_baseline(trades=45, symbols=5),
            allow_release_fixture=True,
        )
        self.assertEqual(payload["stop_reason"], "human_approval_required")
        self.assertTrue(payload["approval_required"])
        self.assertFalse(payload["automatic_champion_promotion"])
        self.assertFalse(payload["strategy_mutated"])

    def test_telegram_autonomous_learning_includes_partner_context(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        partner = payload["autonomous_learning_v2"]["autonomous_quant_partner"]
        self.assertEqual(partner["tool"], "autonomous_quant_research_partner")
        self.assertFalse(partner["strategy_mutated"])
        self.assertFalse(partner["order_executed"])

    def test_hotfix2401_production_wiring_uses_partner_status(self) -> None:
        payload = production_autonomous_research_wiring_release_check()

        self.assertEqual("needs_more_evidence", payload["status"])
        self.assertEqual("needs_more_evidence", payload["promotion_status"])
        self.assertIn("official_market", payload["source_categories_acquired"])
        self.assertTrue(payload["counter_evidence_attempted"])
        self.assertGreater(int(payload["research_iterations"]), 0)
        self.assertGreaterEqual(int(payload["candidate_count"]), 2)

    def test_hotfix2401_telegram_payload_does_not_stop_at_academic_exhaustion(self) -> None:
        baseline = _baseline(trades=1, symbols=1)
        external = {
            "schema_version": 1,
            "state": "academic_content_exhausted",
            "question_id": "research-question:test-2401",
            "discovery_run": {"results": []},
            "normalized_records": [],
            "candidates": [],
            "blockers": ["academic_content_exhausted"],
            "network_executed": True,
        }
        with sqlite3.connect(":memory:") as connection:
            with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
                "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
                return_value=external,
            ):
                payload = telegram_autonomous_learning_payload(
                    connection,
                    "Samsung autonomous production research",
                    symbol="005930",
                )

        learning = payload["autonomous_learning_v2"]
        partner = learning["autonomous_quant_partner"]
        acquisition = partner["source_acquisition"]
        self.assertEqual("autonomous_quant_partner", learning["selected_execution_orchestration"])
        self.assertEqual("academic_content_exhausted", learning["external_research_state"])
        self.assertIn("official_market", acquisition["source_categories_acquired"])
        self.assertEqual("needs_more_evidence", learning["autonomous_quant_partner_promotion_status"])
        self.assertEqual("needs_more_evidence", learning["autonomous_quant_partner_status"])
        self.assertTrue(partner["counter_evidence"]["attempted"])
        self.assertGreater(len(partner["research_iterations"]), 0)
        self.assertGreaterEqual(partner["strategy_tournament"]["candidate_count"], 2)
        self.assertNotIn("deterministic:", str(partner))
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])

    def test_hotfix2401_renderer_shows_partner_orchestration(self) -> None:
        baseline = _baseline(trades=1, symbols=1)
        external = {
            "schema_version": 1,
            "state": "academic_content_exhausted",
            "question_id": "research-question:test-render-2401",
            "discovery_run": {"results": []},
            "normalized_records": [],
            "candidates": [],
            "blockers": ["academic_content_exhausted"],
            "network_executed": True,
        }
        with sqlite3.connect(":memory:") as connection:
            with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
                "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
                return_value=external,
            ):
                payload = telegram_autonomous_learning_payload(connection, "Samsung production wiring", symbol="005930")

        rendered = format_grounded_tool_response("autonomous_learning_research", dict(payload), "Samsung production wiring")

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("Autonomous Quant Partner", rendered)
        self.assertIn("partner_status=needs_more_evidence", rendered)
        self.assertIn("investigated_source_categories=official_market", rendered)
        self.assertIn("counter_evidence_attempted=true", rendered)
        self.assertIn("generated_candidates=2", rendered)
        self.assertIn("research_iterations=", rendered)
        self.assertIn("promotion_status=needs_more_evidence", rendered)


def _baseline(*, trades: int, symbols: int) -> dict[str, object]:
    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": "fp:candidate", "rules": ["breakout", "volume"]}
    return {
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart",
                "fixture_backed": False,
                "rows": 1222,
                "start_date": "2021-07-25",
                "end_date": "2026-07-24",
            }
        },
        "quality": {"status": "pass", "blocking_findings": []},
        "strategy": strategy,
        "validation": {"symbols": symbols, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
        "backtest": {"source": "real", "metrics": {"trade_count": trades, "total_return": 0.12, "mdd": 0.08}},
        "candidates": [
            {
                "candidate_id": "candidate:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": "backtest:candidate",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": trades, "total_return": 0.13, "mdd": 0.07, "profit_factor": 1.4},
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
