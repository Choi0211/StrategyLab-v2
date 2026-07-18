import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace

from gaon.adapters.backtest import BacktestMetrics, BacktestTradeSummary, build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.validation import (
    SQLiteValidationRepository,
    StrategyValidationEngine,
    ValidationPolicy,
    ValidationStatus,
    build_validation_request,
    normalize_drawdown,
)
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyValidationEngineTest(unittest.TestCase):
    def result(self, *, total_return=0.25, max_drawdown=-0.10, profit_factor=1.5, trade_count=40, start="2024-01-01", end="2026-01-01", win_rate=0.55):
        request = build_backtest_request(f"bt-{total_return}-{max_drawdown}-{trade_count}-{start}", "turtle_v5", "sample_krx", start, end, actor_ref="actor:redacted", created_at=NOW)
        return normalize_v1_backtest_result(
            request,
            {
                "engine_version": "v1-fixture",
                "metrics": {
                    "total_return": total_return,
                    "max_drawdown": max_drawdown,
                    "profit_factor": profit_factor,
                    "trade_count": trade_count,
                    "win_rate": win_rate,
                    "start_date": start,
                    "end_date": end,
                },
            },
            generated_at=NOW,
        )

    def validate(self, *results, policy=None):
        request = build_validation_request("validation-test", results, actor_ref="actor:redacted", requested_at=NOW, policy=policy)
        return StrategyValidationEngine(policy).validate(request, results, generated_at=NOW)

    def test_strong_result_passes_and_score_is_deterministic(self) -> None:
        result = self.result()

        first = self.validate(result)
        second = self.validate(result)

        self.assertEqual(first.overall_status, ValidationStatus.PASS)
        self.assertEqual(first.score, second.score)
        self.assertGreaterEqual(first.score, 80)

    def test_excessive_mdd_and_invalid_range_fail(self) -> None:
        report = self.validate(self.result(max_drawdown=45.0))
        invalid = self.validate(self.result(max_drawdown=150.0))

        self.assertEqual(report.overall_status, ValidationStatus.FAIL)
        self.assertIn("maximum drawdown exceeds policy", report.failures)
        self.assertEqual(invalid.overall_status, ValidationStatus.FAIL)
        self.assertEqual(normalize_drawdown(-0.20), 0.20)
        self.assertEqual(normalize_drawdown(20.0), 0.20)

    def test_insufficient_trade_count_and_short_sample_period(self) -> None:
        low_trades = self.validate(self.result(trade_count=12))
        short = self.validate(self.result(start="2025-12-01", end="2026-01-01"))

        self.assertEqual(low_trades.overall_status, ValidationStatus.FAIL)
        self.assertIn("trade count is below policy minimum", low_trades.failures)
        self.assertEqual(short.overall_status, ValidationStatus.REVIEW)
        self.assertIn("sample period is shorter than policy minimum", short.warnings)

    def test_missing_optional_metric_review_and_missing_fingerprint_fail(self) -> None:
        missing_pf = replace(self.result(), metrics=replace(self.result().metrics, profit_factor=None))
        missing_fingerprint = replace(self.result(), fingerprint="", reproducibility={})

        review = self.validate(missing_pf)
        failed = self.validate(missing_fingerprint)

        self.assertEqual(review.overall_status, ValidationStatus.REVIEW)
        self.assertIn("profit_factor is missing", review.unknowns)
        self.assertEqual(failed.overall_status, ValidationStatus.FAIL)
        self.assertIn("reproducibility fingerprint is missing or mismatched", failed.failures)

    def test_hard_fail_overrides_high_score_and_overfitting_warning(self) -> None:
        high_return_bad_mdd = self.result(total_return=5.0, max_drawdown=80.0, profit_factor=4.0, trade_count=100, win_rate=0.95)
        suspicious = self.result(total_return=2.0, max_drawdown=0.1, profit_factor=4.0, trade_count=3, win_rate=0.95)

        failed = self.validate(high_return_bad_mdd)
        warning = self.validate(suspicious)

        self.assertEqual(failed.overall_status, ValidationStatus.FAIL)
        self.assertLessEqual(failed.score, 69)
        self.assertTrue(any("overfitting warning" in item for item in warning.warnings))

    def test_multi_run_consistency_and_catastrophic_window_detection(self) -> None:
        good = self.result(total_return=0.20, max_drawdown=0.10)
        catastrophic = self.result(total_return=-0.10, max_drawdown=0.80)

        report = self.validate(good, good, good, good, catastrophic)

        self.assertEqual(report.overall_status, ValidationStatus.FAIL)
        self.assertIn("at least one validation window has catastrophic drawdown", report.failures)

    def test_event_metrics_and_persistence_round_trip(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repository = SQLiteValidationRepository(store._connection)
            request = build_validation_request("validation-persist", (self.result(),), actor_ref="actor:redacted", requested_at=NOW)
            report = StrategyValidationEngine(repository=repository, event_store=SQLiteEventStore(store._connection), metrics=metrics).validate(request, (self.result(),), generated_at=NOW)
            loaded = repository.get_report("validation-persist")
            events = {event.event_type for event in SQLiteEventStore(store._connection).read_after()}

            self.assertEqual(loaded.to_json(), report.to_json())
            self.assertIn("ValidationCompleted", events)
            self.assertIn("gaon_validation_requests_total", metrics.snapshot().to_text())
            self.assertIn("gaon_validation_pass_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_schema_v12_migrates_to_v13(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (12);
                """
            )
            migrate(connection)

            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'validation_requests'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'validation_reports'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
