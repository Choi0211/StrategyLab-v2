import unittest

from gaon.research.quant_research import (
    AutomatedBacktestResearchEngine,
    CandidateStrategyGenerator,
    EvolutionEngine,
    FlowAnalysisEngine,
    KRXMarketDataTool,
    NewsAnalysisEngine,
    PerformanceComparator,
    QuantResearchOrchestrator,
    SQLiteQuantResearchRepository,
    StrategyImprover,
    ThemeAnalysisEngine,
    _bar_from_json,
    _fixture_news,
)
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-22T00:00:00Z"


class QuantResearchTests(unittest.TestCase):
    def test_krx_market_data_contains_ohlc_value_cap_and_flow(self) -> None:
        payload = KRXMarketDataTool().fetch(symbol="005930", days=20, retrieved_at=NOW)
        self.assertEqual(payload["provider"], "krx-fixture")
        self.assertEqual(len(payload["bars"]), 20)
        first = payload["bars"][0]
        self.assertIn("ohlc", first)
        self.assertIn("trading_value", first)
        self.assertIn("market_cap", first)
        self.assertIn("foreign_net_buy", first)
        self.assertIn("program_net_buy", first)
        self.assertEqual(first["source"]["trust"], "official")

    def test_safe_tool_krx_market_data_is_read_only(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            result = SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit).execute(ToolRequest("krx_market_data", {"symbol": "KOSPI", "days": 5}, "test", NOW))
            self.assertEqual(result.status, "success")
            self.assertEqual(len(result.output["bars"]), 5)
            self.assertEqual(store.tool_audit.list(tool_name="krx_market_data")[0].risk_level, "read_only")
        finally:
            store.close()

    def test_news_theme_flow_strategy_backtest_comparison_pipeline(self) -> None:
        market = KRXMarketDataTool().fetch(symbol="KOSPI", days=20, retrieved_at=NOW)
        bars = tuple(_bar_from_json(item) for item in market["bars"])
        news = NewsAnalysisEngine().analyze(_fixture_news("KOSPI", NOW))
        self.assertTrue(all(-5 <= item.score <= 5 for item in news))
        themes = ThemeAnalysisEngine().analyze(news, bars)
        self.assertIn(themes[0].strength.value, {"leader", "follower", "weak"})
        flow = FlowAnalysisEngine().analyze(bars)
        self.assertGreater(flow.foreign_20d, flow.foreign_5d)
        candidates = CandidateStrategyGenerator().generate(themes, flow)
        self.assertGreaterEqual(len(candidates), 3)
        backtests = AutomatedBacktestResearchEngine().run(candidates)
        self.assertEqual({item.horizon for item in backtests}, {"5y", "3y", "1y", "6m"})
        comparisons = PerformanceComparator().compare(backtests)
        self.assertEqual(len(comparisons), len(candidates))
        improved = StrategyImprover().improve(candidates, comparisons)
        winners = EvolutionEngine().evolve(candidates + improved, comparisons)
        self.assertTrue(winners)
        self.assertFalse(any(item.automatic_promotion for item in comparisons))

    def test_quant_research_report_persists_without_promotion(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            self.assertGreaterEqual(SCHEMA_VERSION, 29)
            report = QuantResearchOrchestrator().run(report_id="unit-quant", generated_at=NOW)
            SQLiteQuantResearchRepository(store._connection).put_report(report)
            count = store._connection.execute("SELECT COUNT(*) FROM quant_research_reports WHERE report_id = 'unit-quant'").fetchone()[0]
            self.assertEqual(int(count), 1)
            self.assertIn("Champion promotion remains disabled", report.summary)
            self.assertFalse(any(item.automatic_promotion for item in report.comparisons))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
