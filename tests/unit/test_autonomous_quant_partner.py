import unittest
from unittest.mock import patch
import os
import sqlite3

from gaon.runtime.research_grounding import format_grounded_tool_response
from gaon.runtime.migrations import migrate
from gaon.knowledge.autonomous_quant_partner import (
    _compare_validation_metrics,
    _release_baseline_with_real_execution_inputs,
    _select_peer_symbols,
    autonomous_quant_partner_payload,
    production_authoritative_source_acquisition_release_check,
    production_autonomous_quant_partner_acceptance_release_check,
    production_counter_evidence_release_check,
    production_autonomous_research_action_loop_release_check,
    production_candidate_freeze_integrity_release_check,
    production_candidate_freeze_release_check,
    production_champion_replacement_release_check,
    production_champion_rollback_release_check,
    production_cost_stress_performance_release_check,
    production_evidence_provenance_release_check,
    production_final_autonomous_research_release_check,
    production_final_conversation_release_check,
    production_final_promotion_readiness_release_check,
    production_final_safety_boundary_release_check,
    production_gaon_v2_completion_release_check,
    production_full_autonomous_quant_research_release_check,
    production_hotfix2561_release_check,
    production_independent_evidence_release_check,
    production_iterative_research_loop_release_check,
    production_learning_memory_closed_loop_release_check,
    production_monte_carlo_robustness_release_check,
    production_multi_source_provider_state_release_check,
    production_multi_symbol_validation_release_check,
    production_no_fabricated_research_results_release_check,
    production_no_fabricated_validation_metrics_release_check,
    production_no_evaluation_window_contamination_release_check,
    production_oos_evaluation_boundary_release_check,
    production_oos_performance_comparison_release_check,
    production_out_of_sample_release_check,
    production_peer_selection_policy_release_check,
    production_parameter_sensitivity_release_check,
    production_promotion_readiness_release_check,
    production_provider_registry_release_check,
    production_real_regime_classification_release_check,
    production_real_cost_stress_execution_release_check,
    production_real_monte_carlo_execution_release_check,
    production_real_monte_carlo_release_check,
    production_real_multi_symbol_execution_release_check,
    production_real_multi_symbol_validation_release_check,
    production_real_oos_execution_release_check,
    production_real_oos_validation_release_check,
    production_real_parameter_variant_execution_release_check,
    production_real_parameter_sensitivity_release_check,
    production_real_regime_execution_release_check,
    production_real_regime_validation_release_check,
    production_real_robustness_execution_release_check,
    production_real_trade_return_series_release_check,
    production_real_transaction_cost_stress_release_check,
    production_real_walk_forward_execution_release_check,
    production_real_walk_forward_release_check,
    production_real_web_news_provider_release_check,
    production_real_youtube_provider_release_check,
    production_regime_validation_release_check,
    production_research_budget_release_check,
    production_research_observability_release_check,
    production_robust_strategy_validation_release_check,
    production_signal_integrity_release_check,
    production_source_diversification_planner_release_check,
    production_sprint249_256_release_check,
    production_strategy_tournament_release_check,
    production_transaction_cost_stress_release_check,
    production_two_stage_approval_release_check,
    production_unified_promotion_readiness_release_check,
    production_validation_execution_vs_result_status_release_check,
    production_validation_sufficiency_v2_release_check,
    production_walk_forward_evaluation_boundary_release_check,
    production_walk_forward_performance_comparison_release_check,
    production_walk_forward_release_check,
)
from gaon.knowledge.telegram_autonomous_learning import (
    production_autonomous_learning_payload_from_baseline,
    production_autonomous_research_wiring_release_check,
    production_autonomous_validation_coverage_release_check,
    production_backtest_signal_diagnostic_release_check,
    production_research_horizon_release_check,
    production_sample_sufficiency_release_check,
    production_validation_coverage_release_check,
    production_validation_window_integrity_release_check,
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

    def test_hotfix2402_release_checks_expose_validation_coverage(self) -> None:
        checks = (
            production_validation_coverage_release_check,
            production_research_horizon_release_check,
            production_sample_sufficiency_release_check,
            production_backtest_signal_diagnostic_release_check,
            production_validation_window_integrity_release_check,
            production_autonomous_validation_coverage_release_check,
        )
        for check in checks:
            with self.subTest(check=check.__name__):
                payload = check()
                self.assertEqual("pass", payload["safety"])
                self.assertNotEqual("unknown", payload["raw_bars"])
                self.assertIn(payload["sample_sufficiency_status"], {"sufficient", "insufficient_trades"})
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])

    def test_hotfix2402_renderer_uses_partner_bar_and_signal_diagnostics(self) -> None:
        baseline = _baseline(trades=1, symbols=1)
        baseline["validation_coverage"] = {
            "raw_bars": 730,
            "usable_bars": 670,
            "warmup_bars": 60,
            "entry_signal_count": 5,
            "exit_signal_count": 1,
            "completed_trade_count": 1,
            "minimum_required_trades": 30,
            "sample_sufficiency_status": "insufficient_trades",
            "sample_sufficiency_reasons": ["insufficient_trades"],
            "requested_start": "2023-07-25",
            "requested_end": "2026-07-24",
            "actual_start": "2023-07-25",
            "actual_end": "2026-07-24",
            "horizon_reason": "extended_for_sample_sufficiency",
            "horizon_extension_attempts": 2,
            "signal_diagnostics": {"breakout_condition_hits": 7, "trend_filter_hits": 6, "volume_filter_hits": 5, "combined_entry_signals": 5},
            "comparison_window_compatible": True,
            "window_fingerprint": "window:test",
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "Samsung validation coverage render",
            symbol="005930",
            mode="research",
            baseline=baseline,
            external_research={"state": "content_unavailable"},
        )
        rendered = format_grounded_tool_response("autonomous_learning_research", dict(payload), "Samsung validation coverage render")

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("bars=730", rendered)
        self.assertIn("usable_bars=670", rendered)
        self.assertIn("entry_signals=5", rendered)
        self.assertIn("sample_status=insufficient_trades", rendered)
        self.assertIn("horizon_extension_attempts=2", rendered)
        self.assertIn("counter_evidence_attempted=true", rendered)
        self.assertIn("generated_candidates=2", rendered)
        self.assertIn("research_iterations=", rendered)
        self.assertIn("promotion_status=needs_more_evidence", rendered)

    def test_sprint241_248_production_grade_release_checks_pass(self) -> None:
        checks = (
            production_signal_integrity_release_check,
            production_multi_symbol_validation_release_check,
            production_real_web_news_provider_release_check,
            production_real_youtube_provider_release_check,
            production_independent_evidence_release_check,
            production_out_of_sample_release_check,
            production_walk_forward_release_check,
            production_regime_validation_release_check,
            production_parameter_sensitivity_release_check,
            production_transaction_cost_stress_release_check,
            production_monte_carlo_robustness_release_check,
            production_unified_promotion_readiness_release_check,
            production_full_autonomous_quant_research_release_check,
            production_no_fabricated_validation_metrics_release_check,
            production_real_multi_symbol_validation_release_check,
            production_real_oos_validation_release_check,
            production_real_walk_forward_release_check,
            production_real_regime_validation_release_check,
            production_real_parameter_sensitivity_release_check,
            production_real_transaction_cost_stress_release_check,
            production_real_monte_carlo_release_check,
            production_real_robustness_execution_release_check,
            production_real_multi_symbol_execution_release_check,
            production_real_oos_execution_release_check,
            production_real_walk_forward_execution_release_check,
            production_real_regime_execution_release_check,
            production_real_parameter_variant_execution_release_check,
            production_real_cost_stress_execution_release_check,
            production_real_trade_return_series_release_check,
            production_real_monte_carlo_execution_release_check,
            production_multi_source_provider_state_release_check,
            production_evidence_provenance_release_check,
            production_autonomous_research_action_loop_release_check,
            production_research_budget_release_check,
            production_final_promotion_readiness_release_check,
            production_no_fabricated_research_results_release_check,
            production_sprint249_256_release_check,
            production_oos_evaluation_boundary_release_check,
            production_walk_forward_evaluation_boundary_release_check,
            production_oos_performance_comparison_release_check,
            production_walk_forward_performance_comparison_release_check,
            production_real_regime_classification_release_check,
            production_cost_stress_performance_release_check,
            production_peer_selection_policy_release_check,
            production_validation_execution_vs_result_status_release_check,
            production_candidate_freeze_integrity_release_check,
            production_no_evaluation_window_contamination_release_check,
            production_hotfix2561_release_check,
            production_final_autonomous_research_release_check,
            production_final_conversation_release_check,
            production_two_stage_approval_release_check,
            production_candidate_freeze_release_check,
            production_champion_replacement_release_check,
            production_champion_rollback_release_check,
            production_final_safety_boundary_release_check,
            production_gaon_v2_completion_release_check,
        )
        for check in checks:
            with self.subTest(check=check.__name__):
                payload = check()
                self.assertEqual("pass", payload["safety"])
                if check.__name__.startswith("production_") and ("2561" in check.__name__ or "completion" in check.__name__ or check.__name__ in {
                    "production_two_stage_approval_release_check",
                    "production_candidate_freeze_release_check",
                    "production_champion_replacement_release_check",
                    "production_champion_rollback_release_check",
                    "production_final_safety_boundary_release_check",
                    "production_final_conversation_release_check",
                    "production_final_autonomous_research_release_check",
                }):
                    self.assertEqual("deterministic_release_validation", payload["check_mode"])
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])

    def test_final_completion_two_stage_approval_contract(self) -> None:
        two_stage = production_two_stage_approval_release_check()
        freeze = production_candidate_freeze_release_check()
        replacement = production_champion_replacement_release_check()
        rollback = production_champion_rollback_release_check()

        self.assertTrue(two_stage["approval_required"])
        self.assertTrue(freeze["checks"]["material_change_invalidates"])
        self.assertTrue(replacement["checks"]["second_approval_required"])
        self.assertTrue(rollback["checks"]["restored_previous_version"])
        for payload in (two_stage, freeze, replacement, rollback):
            self.assertEqual("pass", payload["safety"])
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])

    def test_final_completion_blocks_insufficient_evidence_without_mutation(self) -> None:
        payload = production_final_autonomous_research_release_check()

        self.assertTrue(payload["checks"]["blocked_case_fail_closed"])
        self.assertTrue(payload["checks"]["validation_gates_execute"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])

    def test_hotfix2561_oos_requires_evaluation_sample_not_warmup_profit(self) -> None:
        comparison = _compare_validation_metrics(
            {"trade_count": 8, "total_return": 0.2, "mdd": 0.04},
            {"trade_count": 1, "total_return": 0.5, "mdd": 0.02},
            min_trades=3,
        )

        self.assertEqual("insufficient_oos_sample", comparison["comparison_status"])

    def test_hotfix2561_oos_underperformance_fails_even_after_execution(self) -> None:
        comparison = _compare_validation_metrics(
            {"trade_count": 6, "total_return": 0.12, "mdd": 0.08},
            {"trade_count": 6, "total_return": 0.05, "mdd": 0.07},
            min_trades=3,
        )

        self.assertEqual("fail_underperformed_baseline", comparison["comparison_status"])

    def test_hotfix2561_mdd_underperformance_fails(self) -> None:
        comparison = _compare_validation_metrics(
            {"trade_count": 6, "total_return": 0.12, "mdd": 0.08},
            {"trade_count": 6, "total_return": 0.13, "mdd": 0.18},
            min_trades=3,
        )

        self.assertEqual("fail_underperformed_baseline", comparison["comparison_status"])

    def test_hotfix2561_peer_selection_excludes_primary_and_declares_fallback(self) -> None:
        selection = _select_peer_symbols("005930", baseline={}, budget=type("Budget", (), {"max_symbols": 5})())

        self.assertNotIn("005930", selection["selected_peers"])
        self.assertEqual("peer_selection_unavailable_curated_liquid_krx_fallback_declared", selection["status"])
        self.assertTrue(all("not_etf_etn_spac" in reason for reason in selection["selection_reasons"].values()))

    def test_sprint241_248_renderer_shows_production_grade_validation(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "Samsung production grade autonomous quant research",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=42, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        rendered = format_grounded_tool_response("autonomous_learning_research", dict(payload), "Samsung production grade")

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("Production-Grade Validation", rendered)
        self.assertIn("cross_symbol_status=", rendered)
        self.assertIn("out_of_sample=", rendered)
        self.assertIn("walk_forward=", rendered)
        self.assertIn("monte_carlo=", rendered)

    def test_hotfix2481_missing_robustness_execution_does_not_fabricate_metrics(self) -> None:
        payload = autonomous_quant_partner_payload(
            "Samsung production grade autonomous quant research",
            symbol="005930",
            baseline=_baseline(trades=42, symbols=5),
        )
        grade = payload["production_grade_validation"]
        self.assertFalse(grade["multi_symbol_validation"]["executed"])
        self.assertEqual([], grade["multi_symbol_validation"]["symbols"])
        self.assertEqual("not_run_missing_oos_backtest", grade["out_of_sample"]["status"])
        self.assertEqual([], grade["walk_forward"]["folds"])
        self.assertEqual({}, grade["regime_validation"]["regimes"])
        self.assertEqual([], grade["parameter_sensitivity"]["variants"])
        self.assertEqual([], grade["transaction_cost_stress"]["scenarios"])
        self.assertIsNone(grade["monte_carlo"]["median_outcome"])
        readiness = grade["unified_promotion_readiness"]
        self.assertFalse(readiness["approval_required"])
        self.assertIn("multi_symbol_not_executed", readiness["blockers"])

    def test_sprint249_256_real_execution_release_check_blocks_without_full_approval(self) -> None:
        payload = production_sprint249_256_release_check()
        self.assertEqual("pass", payload["safety"])
        self.assertFalse(payload["approval_required"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])

    def test_sprint249_256_production_peer_validation_uses_real_provider_when_baseline_lacks_peers(self) -> None:
        baseline = dict(_release_baseline_with_real_execution_inputs())
        original_peer_datasets = dict(baseline["peer_datasets"])
        baseline.pop("peer_datasets", None)
        baseline.pop("production_robustness_execution", None)

        class RealPeerProvider:
            def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily"):
                payload = dict(original_peer_datasets[symbol])
                metadata = dict(payload["metadata"])
                metadata.update({"source": "real:yahoo-chart", "fixture_backed": False})
                payload["metadata"] = metadata
                payload["dataset_id"] = f"dataset:{symbol}:real-peer:{start_date}:{end_date}"
                payload["symbols"] = [{"symbol": symbol, "name": symbol, "market": "KOSPI", "exchange": "KRX"}]
                payload["bars"] = [dict(row, symbol=symbol) for row in payload["bars"]]
                from gaon.knowledge.autonomous_quant_partner import _dataset_from_json

                return _dataset_from_json(payload)

        with sqlite3.connect(":memory:") as connection, patch.dict(
            os.environ,
            {"GAON_REAL_MARKET_DATA_ENABLED": "true", "GAON_MARKET_DATA_PROVIDER": "yahoo-chart"},
        ), patch(
            "gaon.research.krx_real_pipeline.build_market_data_provider_from_env",
            return_value=RealPeerProvider(),
        ), patch(
            "gaon.research.krx_real_pipeline._is_research_eligible_quality",
            return_value=True,
        ):
            migrate(connection)
            payload = autonomous_quant_partner_payload(
                "Samsung production real multi-symbol execution",
                symbol="005930",
                baseline=baseline,
                connection=connection,
            )

        multi_symbol = payload["production_grade_validation"]["multi_symbol_validation"]
        self.assertTrue(multi_symbol["executed"])
        self.assertEqual("actual_backtest", multi_symbol["lineage"])
        self.assertEqual(5, multi_symbol["symbols_executed"])
        self.assertEqual(0, multi_symbol["symbols_failed"])
        self.assertTrue(all(not row["fixture_backed"] for row in multi_symbol["symbols"]))


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
