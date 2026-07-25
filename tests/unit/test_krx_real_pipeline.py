import sqlite3
import unittest

from gaon.research.krx_real_pipeline import (
    FieldProvenance,
    KRXDatasetBuilder,
    KRXFixtureMarketDataProvider,
    RealAutonomousResearchPipeline,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    WalkForwardValidator,
    default_execution_assumptions,
)
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


STRATEGY_TEXT = "20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산"


class KRXRealPipelineUnitTests(unittest.TestCase):
    def test_strategy_parser_tracks_user_provenance_without_fixture_leakage(self) -> None:
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        self.assertEqual(spec.entry["breakout_lookback"].value, 20)
        self.assertEqual(spec.entry["breakout_lookback"].provenance, FieldProvenance.USER_PROVIDED)
        payload = str(spec.to_json())
        self.assertNotIn("volume_multiplier", payload)
        self.assertNotIn("max_risk_pct", payload)
        self.assertNotIn("regime_tags", payload)

    def test_dataset_builder_marks_fixture_source_and_reuses_cache(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        builder = KRXDatasetBuilder(connection, KRXFixtureMarketDataProvider())
        first, quality, inserted = builder.build("005930", start_date="2026-01-01", end_date="2026-07-10")
        second, _, inserted_again = builder.build("005930", start_date="2026-01-01", end_date="2026-07-10")
        self.assertTrue(inserted)
        self.assertFalse(inserted_again)
        self.assertTrue(first.metadata.fixture_backed)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(quality.status.value, "pass")

    def test_rule_backtest_is_deterministic_and_applies_costs(self) -> None:
        dataset = KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        assumptions = default_execution_assumptions()
        engine = RuleBasedBacktestEngine()
        first = engine.run("unit-run", spec, dataset, assumptions, generated_at="2026-07-25T00:00:00Z")
        second = engine.run("unit-run", spec, dataset, assumptions, generated_at="2026-07-25T00:00:00Z")
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertGreaterEqual(first.metrics.trade_count, 1)
        self.assertLess(first.trades[0].entry_price, first.trades[0].exit_price)
        self.assertGreater(first.trades[0].entry_price, dataset.bars[65].close)
        self.assertIsNotNone(first.metrics.sharpe)

    def test_walk_forward_uses_chronological_split(self) -> None:
        dataset = KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        report = WalkForwardValidator().validate(spec, dataset, default_execution_assumptions(), run_id="unit-wf", generated_at="2026-07-25T00:00:00Z")
        self.assertEqual(report.validation_id, "validation:unit-wf")
        self.assertGreaterEqual(report.train_metrics.trade_count, 1)
        self.assertGreaterEqual(report.test_metrics.trade_count, 0)

    def test_pipeline_report_is_korean_and_persists_memory(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        report = RealAutonomousResearchPipeline(connection).run(STRATEGY_TEXT, run_id="unit-pipeline", generated_at="2026-07-25T00:00:00Z")
        self.assertIn("[분석 기준]", report.korean_report)
        self.assertIn("source=fixture", report.korean_report)
        self.assertEqual(len(report.candidates), 3)
        self.assertIsNotNone(report.memory_id)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM krx_real_research_memories").fetchone()[0], 1)
        self.assertGreaterEqual(SCHEMA_VERSION, 33)


if __name__ == "__main__":
    unittest.main()
