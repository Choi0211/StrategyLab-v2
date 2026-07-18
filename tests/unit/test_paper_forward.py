import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import PaperTradingForwardTestService, PaperTradingSessionStatus, SQLitePaperTradingSessionRepository
from gaon.adapters.trading import PaperTradingAdapter, SQLiteTradingRepository, TradingStatus
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class PaperForwardTest(unittest.TestCase):
    def bootstrap(self, store, fingerprint="fingerprint1"):
        service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None)
        return service.bootstrap(strategy_ref="turtle_v5", fingerprint=fingerprint, backtest_id=f"backtest:{fingerprint}", actor_ref="actor:redacted", activated_at=NOW)

    def service(self, store, metrics=None, adapter=None):
        return PaperTradingForwardTestService(
            SQLitePaperTradingSessionRepository(store._connection),
            SQLiteChampionRegistryRepository(store._connection),
            trading_repository=SQLiteTradingRepository(store._connection),
            event_store=SQLiteEventStore(store._connection),
            metrics=metrics,
            adapter=adapter,
        )

    def test_only_active_champion_can_create_session(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            active = self.bootstrap(store)
            service = self.service(store)
            session = service.create_session("session1", champion_version_id=active.active_version_id, fingerprint=active.fingerprint, actor_ref="actor:redacted", created_at=NOW)

            self.assertEqual(session.status, PaperTradingSessionStatus.PENDING)
            with self.assertRaises(ValueError):
                service.create_session("session2", champion_version_id="champion-version:default:999", actor_ref="actor:redacted", created_at=NOW)
            with self.assertRaises(ValueError):
                service.create_session("session3", fingerprint="wrongfingerprint", actor_ref="actor:redacted", created_at=NOW)
        finally:
            store.close()

    def test_lifecycle_transitions_and_duplicate_start(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            self.bootstrap(store)
            service = self.service(store)
            service.create_session("session1", actor_ref="actor:redacted", created_at=NOW)
            active = service.start("session1", actor_ref="actor:redacted", at=NOW)
            duplicate = service.start("session1", actor_ref="actor:redacted", at=NOW)
            paused = service.pause("session1", actor_ref="actor:redacted", at=NOW)
            resumed = service.resume("session1", actor_ref="actor:redacted", at=NOW)
            completed = service.complete("session1", actor_ref="actor:redacted", at=NOW)

            self.assertEqual(active.status, PaperTradingSessionStatus.ACTIVE)
            self.assertEqual(duplicate.status, PaperTradingSessionStatus.ACTIVE)
            self.assertEqual(paused.status, PaperTradingSessionStatus.PAUSED)
            self.assertEqual(resumed.status, PaperTradingSessionStatus.ACTIVE)
            self.assertEqual(completed.status, PaperTradingSessionStatus.COMPLETED)
            with self.assertRaises(ValueError):
                service.cancel("session1", actor_ref="actor:redacted", at=NOW)
        finally:
            store.close()

    def test_cancel_and_stale_champion_rejected(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            self.bootstrap(store)
            service = self.service(store)
            session = service.create_session("session1", actor_ref="actor:redacted", created_at=NOW)
            service.cancel("session1", actor_ref="actor:redacted", at=NOW)
            with self.assertRaises(ValueError):
                service.start("session1", actor_ref="actor:redacted", at=NOW)

            service.create_session("session2", actor_ref="actor:redacted", created_at=NOW)
            ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="other", fingerprint="x", backtest_id="b", actor_ref="actor:redacted", activated_at=NOW, slot="other")
            # Mutate the default slot through a direct active write to simulate replacement without depending on Sprint 44 promotion setup.
            current = SQLiteChampionRegistryRepository(store._connection).get_active()
            replaced = type(current)("default", "champion-version:default:2", current.strategy_ref, "fingerprint2", current.source_backtest_id, current.source_validation_id, current.source_evaluation_id, NOW, 2, current.active_version_id)
            SQLiteChampionRegistryRepository(store._connection).put_active(replaced)
            with self.assertRaises(ValueError):
                service.start("session2", actor_ref="actor:redacted", at=NOW)
        finally:
            store.close()

    def test_paper_adapter_reused_summary_events_metrics_and_persistence(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            self.bootstrap(store)
            service = self.service(store, metrics, PaperTradingAdapter())
            service.create_session("session1", actor_ref="actor:redacted", created_at=NOW)
            service.start("session1", actor_ref="actor:redacted", at=NOW)
            result = service.simulate_order("session1", symbol="005930", quantity=1, price=70000, side="buy", actor_ref="actor:redacted", at=NOW)
            summary = service.summary("session1", generated_at=NOW)

            self.assertEqual(result.status, TradingStatus.SIMULATED)
            self.assertEqual(summary.simulated_orders, 1)
            self.assertEqual(summary.fills, 1)
            self.assertEqual(SQLitePaperTradingSessionRepository(store._connection).get_summary("session1").to_json(), summary.to_json())
            self.assertIn("PaperTradingSessionStarted", {event.event_type for event in SQLiteEventStore(store._connection).read_after()})
            self.assertIn("gaon_paper_simulated_orders_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_migration_v16(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "legacy.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (15);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'paper_trading_sessions'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'paper_trading_observations'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'paper_trading_summaries'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
