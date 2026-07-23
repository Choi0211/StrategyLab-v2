import sqlite3
import unittest
from pathlib import Path

from gaon.research.real_research import (
    BacktestComparator,
    BacktestDatasetReference,
    BacktestExecutionAssumptions,
    BacktestRequest,
    BacktestStrategySpec,
    DataQualityEngine,
    DataQualityStatus,
    DeterministicExternalBacktestAdapter,
    FixtureMarketDataProvider,
    MarketBar,
    MarketDataset,
    MarketDataMetadata,
    MarketSymbol,
    RealResearchGateway,
    RealResearchRequest,
    SQLiteDatasetRegistry,
    SQLiteRealResearchRepository,
    StrategyRule,
    backtest_result_from_json,
    turtle_strategy_spec,
)
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-24T00:00:00Z"


class RealResearchIntegrationUnitTests(unittest.TestCase):
    def test_market_data_fixture_has_required_ohlcv_and_provenance(self) -> None:
        dataset = FixtureMarketDataProvider().fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-05")
        self.assertEqual(len(dataset.bars), 5)
        self.assertTrue(dataset.metadata.fixture_backed)
        self.assertEqual(dataset.metadata.market, "KOSPI")
        self.assertTrue(dataset.bars[0].trading_value > 0)

    def test_data_quality_detects_invalid_inputs(self) -> None:
        metadata = MarketDataMetadata("fixture", "KOSPI", "daily", "2026-07-01", "2026-07-03", True, NOW, True)
        symbols = (MarketSymbol("005930", "Samsung", "KOSPI"),)
        bars = (
            MarketBar("2026-07-01", "005930", 10, 12, 9, 11, 100, 1000),
            MarketBar("2026-07-01", "005930", 10, 12, 9, 11, 100, 1000),
            MarketBar("2026-07-03", "005930", 20, 19, 18, 21, -1, 1000),
        )
        report = DataQualityEngine().validate(MarketDataset("dataset:bad", symbols, bars, metadata))
        self.assertEqual(report.status, DataQualityStatus.FAIL)
        codes = {finding.code for finding in report.findings}
        self.assertTrue({"duplicate_bars", "invalid_ohlc", "negative_volume"}.issubset(codes))

    def test_dataset_registry_fingerprint_reuse(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        dataset = FixtureMarketDataProvider().fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-05")
        quality = DataQualityEngine().validate(dataset)
        registry = SQLiteDatasetRegistry(connection)
        self.assertTrue(registry.put_dataset(dataset, quality))
        self.assertFalse(registry.put_dataset(dataset, quality))
        self.assertEqual(registry.get_by_fingerprint(dataset.fingerprint).dataset_id, dataset.dataset_id)  # type: ignore[union-attr]

    def test_strategy_spec_deterministic_and_rejects_invalid_rule(self) -> None:
        first = turtle_strategy_spec("005930")
        second = turtle_strategy_spec("005930")
        self.assertEqual(first.fingerprint, second.fingerprint)
        with self.assertRaises(ValueError):
            StrategyRule("close", "exec", "bad")

    def test_backtest_contract_round_trip_and_cost_assumptions(self) -> None:
        dataset = FixtureMarketDataProvider().fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-05")
        spec = turtle_strategy_spec("005930")
        request = BacktestRequest("unit-request", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), BacktestExecutionAssumptions(0.1, 0.2, 0.3), NOW, "unit")
        result = DeterministicExternalBacktestAdapter().run(request, dataset)
        restored = backtest_result_from_json(result.to_json())
        self.assertEqual(restored.fingerprint, result.fingerprint)
        self.assertEqual(restored.provenance["cost_assumptions"]["tax"], 0.2)

    def test_adapter_failure_timeout_malformed_and_unsupported_engine(self) -> None:
        dataset = FixtureMarketDataProvider().fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-05")
        spec = turtle_strategy_spec("005930")
        request = BacktestRequest("unit-request", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), BacktestExecutionAssumptions(0, 0, 0), NOW, "unit")
        self.assertEqual(DeterministicExternalBacktestAdapter(fail=True).run(request, dataset).status.value, "failed")
        self.assertEqual(DeterministicExternalBacktestAdapter(timeout=True).run(request, dataset).status.value, "timeout")
        self.assertEqual(DeterministicExternalBacktestAdapter(malformed=True).run(request, dataset).status.value, "failed")
        self.assertEqual(DeterministicExternalBacktestAdapter(supported_engine=False).run(request, dataset).status.value, "rejected")

    def test_reproducibility_fingerprint_and_comparison(self) -> None:
        dataset = FixtureMarketDataProvider().fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-05")
        spec = turtle_strategy_spec("005930")
        assumptions = BacktestExecutionAssumptions(0.0001, 0.001, 0.0005)
        first = BacktestRequest("run-a", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), assumptions, NOW, "unit")
        second = BacktestRequest("run-b", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), assumptions, NOW, "unit")
        self.assertEqual(first.fingerprint, second.fingerprint)
        adapter = DeterministicExternalBacktestAdapter()
        comparison = BacktestComparator().compare(adapter.run(first, dataset), adapter.run(second, dataset))
        self.assertEqual(comparison.changed_conditions, ())

    def test_real_research_gateway_persists_and_marks_fixture(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        report = RealResearchGateway(connection=connection).run(RealResearchRequest("unit-real", "005930", "2026-07-01", "2026-07-10"), generated_at=NOW)
        self.assertEqual(report.backtest_result.status.value, "completed")
        self.assertTrue(report.backtest_result.provenance["fixture_backed"])
        self.assertGreaterEqual(SCHEMA_VERSION, 32)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM market_datasets").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM real_backtest_results").fetchone()[0], 1)

    def test_safe_tools_are_read_only(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        executor = SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection))
        result = executor.execute(ToolRequest("data_quality_check", {"symbol": "005930"}, "unit", NOW))
        self.assertEqual(result.status, "success")
        self.assertIn("quality", result.output)
        denied = executor.execute(ToolRequest("data_quality_check", {"symbol": "005930", "shell": "x"}, "unit", NOW))
        self.assertEqual(denied.status, "denied")
        self.assertEqual(SQLiteToolAuditRepository(connection).list(tool_name="data_quality_check")[0].risk_level, "read_only")

    def test_no_private_or_live_keywords_in_public_contract(self) -> None:
        import gaon.research.real_research as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("MyMoneyGuard", source)
        self.assertNotIn("subprocess.run", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("kis", source.casefold())


if __name__ == "__main__":
    unittest.main()
