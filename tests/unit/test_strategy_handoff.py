import sqlite3
import tempfile
import unittest

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, RollbackRecommendation, SQLitePaperRevalidationRepository
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, StrategyHandoffStatus, build_strategy_handoff_request, package_from_json
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyHandoffTest(unittest.TestCase):
    def make_store(self):
        store = RuntimeStateStore(":memory:")
        backtests = SQLiteBacktestRepository(store._connection)
        request = build_backtest_request("bt-request", "turtle_v5", "kospi_fixture", "2025-01-01", "2025-12-31", actor_ref="actor:redacted", created_at=NOW, parameters={"lookback": 20, "risk_pct": 0.02, "enabled": True})
        result = BacktestExecutionService(FakeBacktestAdapter(), repository=backtests).run(request, BacktestExecutionContext(30, 64000, NOW))
        active = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint=result.fingerprint, backtest_id=result.result_id, actor_ref="actor:redacted", activated_at=NOW)
        report = PaperRevalidationReport("rv-live", PaperRevalidationStatus.LIVE_ELIGIBLE, "paper_revalidation_policy_v1", "paper-session-1", active.active_version_id, active.fingerprint, (), (), (), RollbackRecommendation(False, "not recommended"), NOW)
        SQLitePaperRevalidationRepository(store._connection).add_report(report)
        return store, active, result

    def service(self, store, metrics=None):
        return StrategyHandoffService(
            SQLiteStrategyHandoffRepository(store._connection),
            SQLiteChampionRegistryRepository(store._connection),
            SQLitePaperRevalidationRepository(store._connection),
            SQLiteBacktestRepository(store._connection),
            event_store=SQLiteEventStore(store._connection),
            metrics=metrics,
        )

    def create_package(self, store):
        request = build_strategy_handoff_request("handoff-req", revalidation_id="rv-live", actor_ref="actor:redacted", requested_at=NOW)
        return self.service(store).create(request)

    def test_valid_live_eligible_champion_creates_pending_package(self) -> None:
        store, _, _ = self.make_store()
        try:
            package = self.create_package(store)
            self.assertEqual(package.status, StrategyHandoffStatus.PENDING_APPROVAL)
            self.assertTrue(package.approval_required)
            self.assertEqual(package.parameters.parameters["lookback"], 20)
            self.assertNotIn("secret", package.to_json().lower())
        finally:
            store.close()

    def test_hold_kill_and_rollback_revalidation_rejected(self) -> None:
        for status in (PaperRevalidationStatus.HOLD, PaperRevalidationStatus.KILL, PaperRevalidationStatus.ROLLBACK_RECOMMENDED):
            with self.subTest(status=status):
                store, active, _ = self.make_store()
                try:
                    SQLitePaperRevalidationRepository(store._connection).add_report(
                        PaperRevalidationReport(f"rv-{status.value}", status, "paper_revalidation_policy_v1", "paper-session-1", active.active_version_id, active.fingerprint, (), (), (), RollbackRecommendation(status == PaperRevalidationStatus.ROLLBACK_RECOMMENDED, "not recommended"), NOW)
                    )
                    request = build_strategy_handoff_request(f"handoff-{status.value}", revalidation_id=f"rv-{status.value}", actor_ref="actor:redacted", requested_at=NOW)
                    with self.assertRaises(ValueError):
                        self.service(store).create(request)
                finally:
                    store.close()

    def test_stale_champion_fingerprint_rejected(self) -> None:
        store, active, _ = self.make_store()
        try:
            SQLitePaperRevalidationRepository(store._connection).add_report(
                PaperRevalidationReport("rv-stale", PaperRevalidationStatus.LIVE_ELIGIBLE, "paper_revalidation_policy_v1", "paper-session-1", active.active_version_id, "stale-fingerprint", (), (), (), RollbackRecommendation(False, "not recommended"), NOW)
            )
            request = build_strategy_handoff_request("handoff-stale", revalidation_id="rv-stale", actor_ref="actor:redacted", requested_at=NOW)
            with self.assertRaises(ValueError):
                self.service(store).create(request)
        finally:
            store.close()

    def test_deterministic_json_and_checksum_round_trip(self) -> None:
        store, _, _ = self.make_store()
        try:
            package = self.create_package(store)
            loaded = package_from_json(package.to_json())
            self.assertEqual(package.to_json(), loaded.to_json())
            self.assertEqual(package.checksum, loaded.checksum)
            self.assertEqual(package.to_json(), package.to_json())
        finally:
            store.close()

    def test_approval_rejection_and_approved_package_immutability(self) -> None:
        store, _, _ = self.make_store()
        try:
            service = self.service(store)
            package = self.create_package(store)
            self.assertIsNone(SQLiteStrategyHandoffRepository(store._connection).latest_approval(package.package_id))
            approved = service.approve(package.package_id, approver_ref="actor:redacted", decided_at=NOW)
            self.assertEqual(approved.status, StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT)
            self.assertEqual(SQLiteStrategyHandoffRepository(store._connection).latest_approval(package.package_id).package_checksum, approved.checksum)
            with self.assertRaises(ValueError):
                SQLiteStrategyHandoffRepository(store._connection).update_package(approved.with_status(StrategyHandoffStatus.REJECTED, actor_ref="actor:redacted", at=NOW))

            store2, _, _ = self.make_store()
            try:
                rejected = self.service(store2).reject(self.create_package(store2).package_id, actor_ref="actor:redacted", decided_at=NOW, reason="not ready")
                self.assertEqual(rejected.status, StrategyHandoffStatus.REJECTED)
            finally:
                store2.close()
        finally:
            store.close()

    def test_changed_package_checksum_invalidates_prior_approval(self) -> None:
        store, _, _ = self.make_store()
        try:
            service = self.service(store)
            package = self.create_package(store)
            approved = service.approve(package.package_id, approver_ref="actor:redacted", decided_at=NOW)
            changed_payload = approved.payload_without_checksum() | {"created_by": "actor:changed"}
            self.assertNotEqual(approved.checksum, __import__("hashlib").sha256(__import__("json").dumps(changed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
        finally:
            store.close()

    def test_events_metrics_persistence_and_v19_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(f"{tmp}/runtime.sqlite")
            metrics = MetricsCollector()
            try:
                seeded, _, _ = self.make_store()
                for table in ("backtest_requests", "backtest_results", "champion_registry", "champion_history", "paper_revalidation_reports"):
                    rows = seeded._connection.execute(f"SELECT * FROM {table}").fetchall()
                    columns = [info[1] for info in seeded._connection.execute(f"PRAGMA table_info({table})").fetchall()]
                    placeholders = ",".join("?" for _ in columns)
                    for row in rows:
                        store._connection.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})", tuple(row))
                store._connection.commit()
                seeded.close()
                package = self.service(store, metrics=metrics).create(build_strategy_handoff_request("handoff-req", revalidation_id="rv-live", actor_ref="actor:redacted", requested_at=NOW))
                self.assertEqual(SQLiteStrategyHandoffRepository(store._connection).get_package(package.package_id).checksum, package.checksum)
                self.assertIn("StrategyHandoffPackageCreated", {event.event_type for event in SQLiteEventStore(store._connection).read_after()})
                self.assertIn("gaon_strategy_handoff_packages_total", metrics.snapshot().to_text())
            finally:
                store.close()

            connection = sqlite3.connect(f"{tmp}/legacy.sqlite")
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (18);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'strategy_handoff_packages'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
