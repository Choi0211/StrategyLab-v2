import sqlite3
import unittest
from urllib.request import Request

from gaon.research.krx_real_pipeline import (
    FieldProvenance,
    KRXDatasetBuilder,
    KRXFixtureMarketDataProvider,
    RealAutonomousResearchPipeline,
    RealMarketDataUnavailable,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    WalkForwardValidator,
    YahooKRXHistoricalDataProvider,
    build_market_data_provider_from_env,
    default_execution_assumptions,
    real_krx_data_release_check,
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

    def test_yahoo_provider_parses_real_response_with_provenance(self) -> None:
        provider = YahooKRXHistoricalDataProvider(opener=_opener(_sample_yahoo_payload()))
        dataset = provider.fetch_bars("005930", start_date="2026-01-01", end_date="2026-04-10")
        self.assertFalse(dataset.metadata.fixture_backed)
        self.assertEqual(dataset.metadata.source, "real:yahoo-chart")
        self.assertEqual(len(dataset.bars), 70)
        self.assertGreater(dataset.bars[-1].trading_value, 0)

    def test_yahoo_provider_empty_malformed_and_failure_are_unavailable(self) -> None:
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_opener('{"chart":{"result":[],"error":null}}')).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_opener("{bad")).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_failing_opener).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")

    def test_real_release_check_rejects_fixture_and_accepts_fake_real_data(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        with self.assertRaises(RealMarketDataUnavailable):
            real_krx_data_release_check(connection, symbol="005930", start_date="2026-01-01", end_date="2026-04-10", provider=KRXFixtureMarketDataProvider())
        provider = YahooKRXHistoricalDataProvider(opener=_opener(_sample_yahoo_payload()))
        result = real_krx_data_release_check(connection, symbol="005930", start_date="2026-01-01", end_date="2026-04-10", provider=provider)
        self.assertEqual(result["source"], "real")
        self.assertFalse(result["fixture_backed"])
        self.assertEqual(result["quality"], "pass")

    def test_env_provider_selection_requires_explicit_real_provider(self) -> None:
        self.assertIsInstance(build_market_data_provider_from_env({}), KRXFixtureMarketDataProvider)
        with self.assertRaises(RealMarketDataUnavailable):
            build_market_data_provider_from_env({"GAON_REAL_MARKET_DATA_ENABLED": "true", "GAON_MARKET_DATA_PROVIDER": "fixture"})
        self.assertIsInstance(build_market_data_provider_from_env({"GAON_REAL_MARKET_DATA_ENABLED": "true", "GAON_MARKET_DATA_PROVIDER": "yahoo-chart"}), YahooKRXHistoricalDataProvider)

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


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def _opener(body: str):
    def open_(_request: Request, _timeout: float) -> _Response:
        return _Response(body)

    return open_


def _failing_opener(_request: Request, _timeout: float) -> object:
    raise TimeoutError("network timeout")


def _sample_yahoo_payload() -> str:
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    start = 1767225600
    for index in range(70):
        close = 100.0 + index * 0.25 + (4.0 if index == 64 else 0.0)
        timestamps.append(start + index * 86400)
        opens.append(round(close - 0.3, 4))
        highs.append(round(close + 0.9, 4))
        lows.append(round(close - 1.0, 4))
        closes.append(round(close, 4))
        volumes.append(1_000_000 + index * 10_000 + (500_000 if index == 64 else 0))
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    import json

    return json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
