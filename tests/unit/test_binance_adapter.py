import unittest
from pathlib import Path


class BinanceAdapterConfigFromEnvTests(unittest.TestCase):
    def test_defaults_to_production_state_dir_when_env_unset(self) -> None:
        from gaon.adapters.binance import DEFAULT_BINANCE_STATE_DIR, build_binance_adapter_config_from_env

        config = build_binance_adapter_config_from_env({})
        self.assertEqual(config.state_dir, Path(DEFAULT_BINANCE_STATE_DIR))
        self.assertEqual(config.research_dir, config.state_dir)

    def test_research_dir_can_be_configured_separately(self) -> None:
        from gaon.adapters.binance import build_binance_adapter_config_from_env

        config = build_binance_adapter_config_from_env(
            {"GAON_BINANCE_STATE_DIR": "/opt/binance-trading", "GAON_BINANCE_RESEARCH_DIR": "/opt/binance-research"}
        )
        self.assertEqual(config.state_dir, Path("/opt/binance-trading"))
        self.assertEqual(config.research_dir, Path("/opt/binance-research"))


class BinanceStateReaderReadOnlyTests(unittest.TestCase):
    def test_reader_and_snapshot_expose_no_write_capable_methods(self) -> None:
        from gaon.adapters.binance import BinanceChampionStrategySnapshot, BinanceStateReader

        for candidate in (BinanceStateReader, BinanceChampionStrategySnapshot):
            for name in dir(candidate):
                self.assertFalse(
                    name.startswith(("write", "save", "update", "set_")),
                    f"{candidate.__name__}.{name} looks like a write-capable method; this adapter must be read-only",
                )

    def test_no_order_execution_method_exists_anywhere_in_module(self) -> None:
        import gaon.adapters.binance as binance_module

        for forbidden in ("execute_order", "propose_order", "approve_order", "simulate_order", "place_order", "futures_create_order"):
            self.assertFalse(
                hasattr(binance_module, forbidden),
                f"gaon.adapters.binance must never define {forbidden}",
            )


class BinanceAdapterReadOnlyReleaseCheckTests(unittest.TestCase):
    """Production has no Binance integration yet; this proves the read-only
    adapter (account/positions/trade-events/Champion-params/BIN-PA research
    reads, plus the champion/challenger comparison for a BIN-PA challenger)
    works end to end against fixture data, with zero writes anywhere, before
    it is ever pointed at the real /opt/binance-trading directory. Following
    this codebase's caller-wiring convention - see
    PromotionReadinessReachabilityReleaseCheckTests in
    test_research_mission.py - this test IS the caller."""

    def test_release_check_passes_and_confirms_invariants(self) -> None:
        from gaon.adapters.binance import production_binance_adapter_read_only_release_check

        payload = production_binance_adapter_read_only_release_check()
        for key in (
            "account_read_correctly",
            "positions_read_correctly",
            "trades_read_correctly",
            "champion_strategy_is_read_only_snapshot",
            "strategy_params_file_untouched_by_read",
            "family_summary_read_correctly",
            "health_check_reports_healthy_fixture",
            "no_write_method_on_state_reader",
            "no_write_method_on_champion_snapshot",
            "no_order_execution_methods_exist",
            "champion_challenger_report_generated",
            "champion_challenger_decision_is_research_only",
            "validation_report_generated",
        ):
            self.assertTrue(payload[key], key)
        self.assertIn(payload["champion_challenger_decision"], ("keep_champion", "promotion_candidate", "review"))
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertEqual(payload["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.adapters.binance import production_binance_adapter_read_only_release_check

        first = production_binance_adapter_read_only_release_check()
        second = production_binance_adapter_read_only_release_check()
        self.assertEqual(dict(first), dict(second))


class BinanceAdapterCliWiringTests(unittest.TestCase):
    """CLI wiring for production_binance_adapter_read_only_release_check,
    following the exact existing gaon-production-*-release-check pattern."""

    def test_binance_adapter_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-production-binance-adapter-read-only-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-production-binance-adapter-read-only-release-check: PASS", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("order_executed=false", printed)
        self.assertIn("champion_promoted=false", printed)
        self.assertIn("approval_bypassed=false", printed)


if __name__ == "__main__":
    unittest.main()
