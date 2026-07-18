import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.backtest import (
    BacktestExecutionContext,
    BacktestExecutionService,
    BacktestStatus,
    FakeBacktestAdapter,
    LocalProcessBacktestAdapter,
    LocalProcessResult,
    SQLiteBacktestRepository,
    build_backtest_request,
    normalize_v1_backtest_result,
)
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class BacktestAdapterFoundationTest(unittest.TestCase):
    def request(self, request_id: str = "bt-1", *, strategy: str = "turtle_v5", start: str = "2024-01-01", end: str = "2026-01-01"):
        return build_backtest_request(request_id, strategy, "sample_krx", start, end, actor_ref="actor:redacted", created_at=NOW)

    def context(self) -> BacktestExecutionContext:
        return BacktestExecutionContext(30, 64_000, NOW)

    def test_valid_request_fingerprint_and_fake_result_are_deterministic(self) -> None:
        request = self.request()
        adapter = FakeBacktestAdapter()

        result = adapter.run_backtest(request, self.context())
        repeated = adapter.run_backtest(request, self.context())

        self.assertEqual(result.status, BacktestStatus.COMPLETED)
        self.assertEqual(result.fingerprint, repeated.fingerprint)
        self.assertEqual(result.metrics.trade_count, 12)
        self.assertIn("real v1 engine not invoked", result.warnings[0])

    def test_invalid_strategy_and_period_are_rejected(self) -> None:
        adapter = FakeBacktestAdapter()
        result = adapter.run_backtest(self.request(strategy="unknown"), self.context())

        self.assertEqual(result.status, BacktestStatus.REJECTED)
        self.assertIn("unsupported strategy", result.errors)
        with self.assertRaises(ValueError):
            self.request(start="2026-01-01", end="2024-01-01")

    def test_result_normalization_allows_missing_optional_metrics(self) -> None:
        request = self.request()
        result = normalize_v1_backtest_result(request, {"engine_version": "v1.0", "metrics": {"total_return": 0.1}}, generated_at=NOW)

        self.assertEqual(result.status, BacktestStatus.COMPLETED)
        self.assertEqual(result.metrics.total_return, 0.1)
        self.assertIsNone(result.metrics.sharpe_ratio)
        self.assertEqual(result.raw_engine_version, "v1.0")

    def test_local_process_timeout_nonzero_invalid_json_and_output_bound(self) -> None:
        request = self.request()
        cases = (
            (LocalProcessResult(0, "{}", "", 30, timed_out=True), BacktestStatus.TIMEOUT, "timed out"),
            (LocalProcessResult(2, "{}", "boom", 30), BacktestStatus.FAILED, "non-zero"),
            (LocalProcessResult(0, "{bad", "", 30), BacktestStatus.FAILED, "invalid JSON"),
            (LocalProcessResult(0, "x" * 2048, "", 30), BacktestStatus.FAILED, "exceeded bound"),
        )
        for process_result, expected_status, expected_message in cases:
            adapter = LocalProcessBacktestAdapter(_Invoker(process_result))
            result = adapter.run_backtest(request, BacktestExecutionContext(30, 1024, NOW))
            self.assertEqual(result.status, expected_status)
            self.assertTrue(any(expected_message in error for error in result.errors))

    def test_persistence_duplicate_events_and_metrics(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = SQLiteBacktestRepository(store._connection)
            event_store = SQLiteEventStore(store._connection)
            service = BacktestExecutionService(FakeBacktestAdapter(), repository=repo, event_store=event_store, metrics=metrics)
            request = self.request("persist")

            first = service.run(request, self.context())
            duplicate = service.run(request, self.context())
            results = repo.list_results()
            events = {event.event_type for event in event_store.read_after()}

            self.assertEqual(first.status, BacktestStatus.COMPLETED)
            self.assertEqual(duplicate.status, BacktestStatus.REJECTED)
            self.assertEqual(len(results), 1)
            self.assertIn("BacktestRequested", events)
            self.assertIn("BacktestCompleted", events)
            self.assertIn("gaon_backtest_requests_total", metrics.snapshot().to_text())
            self.assertIn("gaon_backtest_rejections_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_schema_v11_migrates_to_v12(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (11);
                """
            )
            migrate(connection)
            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            request_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'backtest_requests'").fetchone()
            result_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'backtest_results'").fetchone()

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIsNotNone(request_table)
            self.assertIsNotNone(result_table)
            connection.close()


class _Invoker:
    def __init__(self, result: LocalProcessResult) -> None:
        self.result = result

    def invoke(self, request_json: str, *, timeout_seconds: int, max_output_bytes: int) -> LocalProcessResult:
        return self.result


if __name__ == "__main__":
    unittest.main()
