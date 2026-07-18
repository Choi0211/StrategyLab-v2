import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.trading import (
    OrderType,
    PaperTradingAdapter,
    SQLiteTradingRepository,
    TradingExecutionService,
    TradingIntent,
    TradingRiskPolicy,
    TradingStatus,
    build_trading_request,
)
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class TradingAdapterFoundationTest(unittest.TestCase):
    def request(self, request_id: str = "trade-1", *, intent: TradingIntent = TradingIntent.SIMULATE_BUY, symbol: str = "005930", quantity: float = 1.0, price: float = 70000.0):
        return build_trading_request(request_id, intent, symbol=symbol, quantity=quantity, price=price, actor_ref="actor:redacted", created_at=NOW, idempotency_key=request_id)

    def test_account_snapshot_position_snapshot_and_health(self) -> None:
        adapter = PaperTradingAdapter()

        self.assertTrue(adapter.health_check()[0])
        self.assertEqual(adapter.get_account_snapshot().currency, "KRW")
        self.assertEqual(adapter.get_positions(), ())

    def test_valid_simulated_buy_and_sell(self) -> None:
        adapter = PaperTradingAdapter()
        service = TradingExecutionService(adapter, TradingRiskPolicy())

        buy = service.execute(self.request("buy-1", intent=TradingIntent.SIMULATE_BUY))
        sell = service.execute(self.request("sell-1", intent=TradingIntent.SIMULATE_SELL))

        self.assertEqual(buy.status, TradingStatus.SIMULATED)
        self.assertEqual(sell.status, TradingStatus.SIMULATED)
        self.assertIn("no live order", buy.message)

    def test_risk_rejections_are_structured(self) -> None:
        service = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy(max_notional=1000.0))

        zero_quantity = service.execute(self.request("bad-qty", quantity=0.0))
        high_notional = service.execute(self.request("bad-notional", quantity=10.0, price=70000.0))
        self.assertEqual(zero_quantity.status, TradingStatus.REJECTED)
        self.assertIn("quantity must be positive", zero_quantity.message)
        self.assertEqual(high_notional.status, TradingStatus.REJECTED)
        self.assertIn("max notional exceeded", high_notional.message)
        with self.assertRaises(ValueError):
            self.request("bad-symbol", symbol="BAD SYMBOL")

    def test_unsupported_order_type_disabled_adapter_and_live_execution_blocked(self) -> None:
        adapter = PaperTradingAdapter(adapter_enabled=False)
        service = TradingExecutionService(adapter, TradingRiskPolicy(allowed_order_types=(OrderType.LIMIT,)))

        market_request = build_trading_request("market", TradingIntent.SIMULATE_BUY, symbol="005930", quantity=1.0, actor_ref="actor:redacted", created_at=NOW)
        live_request = build_trading_request("live", TradingIntent.LIVE_BUY, symbol="005930", quantity=1.0, price=70000.0, actor_ref="actor:redacted", created_at=NOW)

        market = service.execute(market_request)
        live = service.execute(live_request)

        self.assertEqual(market.status, TradingStatus.REJECTED)
        self.assertIn("trading adapter is disabled", market.message)
        self.assertIn("unsupported order type", market.message)
        self.assertEqual(live.status, TradingStatus.BLOCKED)
        self.assertIn("live trading is not implemented", live.message)
        self.assertTrue(live.decision.approval_required)

    def test_duplicate_request_persistence_events_and_metrics(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = SQLiteTradingRepository(store._connection)
            event_store = SQLiteEventStore(store._connection)
            service = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy(), repository=repo, event_store=event_store, metrics=metrics)
            request = self.request("duplicate")

            first = service.execute(request)
            duplicate = service.execute(request)
            results = repo.list_results()
            events = {event.event_type for event in event_store.read_after()}

            self.assertEqual(first.status, TradingStatus.SIMULATED)
            self.assertEqual(duplicate.status, TradingStatus.REJECTED)
            self.assertEqual(len(results), 1)
            self.assertIn("TradingRequestCreated", events)
            self.assertIn("PaperTradeCompleted", events)
            self.assertIn("gaon_trading_requests_total", metrics.snapshot().to_text())
            self.assertIn("gaon_trading_rejections_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_adapter_failure_does_not_crash_runtime(self) -> None:
        service = TradingExecutionService(PaperTradingAdapter(fail_simulation=True), TradingRiskPolicy())

        result = service.execute(self.request("failure"))

        self.assertEqual(result.status, TradingStatus.FAILED)
        self.assertEqual(result.decision.reasons, ("RuntimeError",))

    def test_schema_v10_migrates_to_v11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (10);
                """
            )
            migrate(connection)
            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            request_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'trading_requests'").fetchone()
            result_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'trading_results'").fetchone()

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIsNotNone(request_table)
            self.assertIsNotNone(result_table)
            connection.close()


if __name__ == "__main__":
    unittest.main()
