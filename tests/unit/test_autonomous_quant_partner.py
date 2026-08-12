import unittest

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
from gaon.knowledge.telegram_autonomous_learning import production_autonomous_learning_payload_from_baseline


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
        )
        self.assertEqual(payload["validation_sufficiency_v2"]["status"], "insufficient_sample")
        self.assertFalse(payload["approval_required"])
        self.assertIn("검증 부족", payload["telegram_progress"])

    def test_sufficient_real_evidence_stops_at_human_approval_boundary(self) -> None:
        payload = autonomous_quant_partner_payload(
            "승격 승인 전까지 연구해줘",
            symbol="005930",
            baseline=_baseline(trades=45, symbols=5),
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
