import unittest

from gaon.research.quant_scientist import (
    AIScientistOrchestrator,
    EnsembleSignal,
    FeatureDiscoveryEngine,
    FeatureSelectionEngine,
    MarketRegimeDetector,
    MonteCarloSimulator,
    SQLiteAIScientistRepository,
    WalkForwardValidator,
    _returns,
)
from gaon.research.quant_research import KRXMarketDataTool, _bar_from_json
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-22T00:00:00Z"


class QuantScientistTests(unittest.TestCase):
    def _bars(self):
        market = KRXMarketDataTool().fetch(symbol="KOSPI", days=60, retrieved_at=NOW)
        return tuple(_bar_from_json(item) for item in market["bars"])

    def test_feature_discovery_generates_required_features_with_source(self) -> None:
        features = FeatureDiscoveryEngine().discover(self._bars())
        self.assertEqual({item.name for item in features}, {"volume_change", "volatility_5d", "vwap", "gap", "relative_strength"})
        self.assertTrue(all(len(item.values) == 60 for item in features))
        self.assertTrue(all(item.source_ref == "krx-fixture" for item in features))
        self.assertTrue(all(item.source_trust == "official" for item in features))
        self.assertTrue(all(item.source_freshness == "fresh" for item in features))

    def test_feature_selection_scores_importance(self) -> None:
        bars = self._bars()
        features = FeatureDiscoveryEngine().discover(bars)
        selected = FeatureSelectionEngine().select(features, _returns(tuple(bar.close for bar in bars)))
        self.assertEqual(len(selected), 3)
        self.assertGreaterEqual(selected[0].importance, selected[-1].importance)
        self.assertTrue(all(item.importance >= 0 for item in selected))

    def test_scientist_pipeline_covers_validation_regime_portfolio_and_explanation(self) -> None:
        report = AIScientistOrchestrator().run(report_id="unit-ai-scientist", generated_at=NOW)
        self.assertEqual(len(report.selected_features), 3)
        self.assertEqual(len(report.walk_forward), 3)
        self.assertTrue(all(window.window_id.startswith("wf-") for window in report.walk_forward))
        self.assertGreaterEqual(report.monte_carlo.robustness_score, 0.0)
        self.assertGreaterEqual(report.regime.confidence, 0.0)
        self.assertTrue(report.portfolio.weights)
        self.assertIn(report.ensemble.signal, {EnsembleSignal.LONG_BIAS, EnsembleSignal.NEUTRAL, EnsembleSignal.RISK_OFF})
        self.assertIn("approval", " ".join(report.explanation.rationale).casefold())
        self.assertFalse(bool(report.champion_comparison["automatic_promotion"]))

    def test_ai_scientist_report_persists_without_promotion(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            self.assertGreaterEqual(SCHEMA_VERSION, 30)
            report = AIScientistOrchestrator().run(report_id="unit-ai-scientist", generated_at=NOW)
            SQLiteAIScientistRepository(store._connection).put_report(report)
            count = store._connection.execute("SELECT COUNT(*) FROM ai_scientist_reports WHERE report_id = 'unit-ai-scientist'").fetchone()[0]
            importance_rows = store._connection.execute("SELECT COUNT(*) FROM ai_feature_importance WHERE report_id = 'unit-ai-scientist'").fetchone()[0]
            self.assertEqual(int(count), 1)
            self.assertEqual(int(importance_rows), 3)
            self.assertFalse(bool(report.champion_comparison["automatic_promotion"]))
        finally:
            store.close()

    def test_feature_discovery_safe_tool_is_read_only(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            result = SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit).execute(
                ToolRequest("feature_discovery", {"symbol": "KOSPI", "days": 10}, "test", NOW)
            )
            self.assertEqual(result.status, "success")
            self.assertEqual(len(result.output["features"]), 5)
            self.assertEqual(store.tool_audit.list(tool_name="feature_discovery")[0].risk_level, "read_only")
        finally:
            store.close()

    def test_low_level_engines_reject_empty_inputs(self) -> None:
        with self.assertRaises(ValueError):
            FeatureDiscoveryEngine().discover(())
        with self.assertRaises(ValueError):
            from gaon.research.quant_scientist import PortfolioOptimizer

            PortfolioOptimizer().optimize(())


if __name__ == "__main__":
    unittest.main()
