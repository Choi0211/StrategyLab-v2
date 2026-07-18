import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, RollbackRecommendation, SQLitePaperRevalidationRepository
from gaon.adapters.strategy_execution import SQLiteStrategyExecutionRepository, StrategyExecutionMode, StrategyExecutionPolicy, StrategyExecutionRuntime, StrategyExecutionStatus, build_strategy_execution_request
from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyExecutionTest(unittest.TestCase):
    def bootstrap(self, store):
        return ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint="fingerprint1", backtest_id="backtest1", actor_ref="actor:redacted", activated_at=NOW)

    def runtime(self, store, *, policy=None, metrics=None):
        return StrategyExecutionRuntime(SQLiteStrategyExecutionRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), revalidations=SQLitePaperRevalidationRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=metrics, policy=policy)

    def add_revalidation(self, store, status: PaperRevalidationStatus, revalidation_id="rv1"):
        report = PaperRevalidationReport(revalidation_id, status, "paper_revalidation_policy_v1", "paper1", "champion-version:default:1", "fingerprint1", (), (), (), RollbackRecommendation(False, "not recommended"), NOW)
        SQLitePaperRevalidationRepository(store._connection).add_report(report)
        return report

    def test_default_mode_disabled_and_config_defaults(self) -> None:
        self.assertEqual(StrategyExecutionPolicy().default_mode, StrategyExecutionMode.DISABLED)
        self.assertEqual(load_runtime_config({}).execution_mode, "disabled")
        self.assertFalse(GaonRuntimeConfig().live_trading_enabled)

    def test_missing_and_stale_champion_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            plan = self.runtime(store).plan(build_strategy_execution_request("req1", StrategyExecutionMode.PAPER, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(plan.status, StrategyExecutionStatus.BLOCKED)
            self.bootstrap(store)
            stale = self.runtime(store).plan(build_strategy_execution_request("req2", StrategyExecutionMode.PAPER, actor_ref="actor:redacted", requested_at=NOW, champion_version_id="old"))
            self.assertEqual(stale.status, StrategyExecutionStatus.BLOCKED)
            self.assertIn("stale", stale.decision.reason)
        finally:
            store.close()

    def test_paper_plan_and_execution_reuse_adapter(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            self.bootstrap(store)
            runtime = self.runtime(store, metrics=metrics)
            plan = runtime.plan(build_strategy_execution_request("req-paper", StrategyExecutionMode.PAPER, actor_ref="actor:redacted", requested_at=NOW))
            run = runtime.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)

            self.assertEqual(plan.status, StrategyExecutionStatus.READY)
            self.assertEqual(run.status, StrategyExecutionStatus.COMPLETED)
            self.assertIn("gaon_paper_execution_runs_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_live_gates_hold_kill_rollback_and_live_eligible_still_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            self.bootstrap(store)
            runtime = self.runtime(store, policy=StrategyExecutionPolicy(live_trading_enabled=True))
            for status, reason in (
                (PaperRevalidationStatus.HOLD, "HOLD"),
                (PaperRevalidationStatus.KILL, "KILL"),
                (PaperRevalidationStatus.ROLLBACK_RECOMMENDED, "rollback"),
            ):
                with self.subTest(status=status):
                    self.add_revalidation(store, status, f"rv-{status.value}")
                    plan = runtime.plan(build_strategy_execution_request(f"req-{status.value}", StrategyExecutionMode.LIVE, actor_ref="actor:redacted", requested_at=NOW, revalidation_id=f"rv-{status.value}"))
                    self.assertEqual(plan.status, StrategyExecutionStatus.BLOCKED)
                    self.assertIn(reason.lower(), plan.decision.reason.lower())
            self.add_revalidation(store, PaperRevalidationStatus.LIVE_ELIGIBLE, "rv-live")
            plan = runtime.plan(build_strategy_execution_request("req-live", StrategyExecutionMode.LIVE, actor_ref="actor:redacted", requested_at=NOW, revalidation_id="rv-live"))
            self.assertEqual(plan.status, StrategyExecutionStatus.BLOCKED)
            self.assertIn("broker adapter unavailable", plan.decision.reason)
        finally:
            store.close()

    def test_persistence_restart_recovery_events_metrics_and_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                self.bootstrap(store)
                metrics = MetricsCollector()
                runtime = self.runtime(store, metrics=metrics)
                plan = runtime.plan(build_strategy_execution_request("req-paper", StrategyExecutionMode.PAPER, actor_ref="actor:redacted", requested_at=NOW))
                run = runtime.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
                self.assertIn("StrategyExecutionCompleted", {event.event_type for event in SQLiteEventStore(store._connection).read_after()})
            finally:
                store.close()
            reopened = RuntimeStateStore(db)
            try:
                repo = SQLiteStrategyExecutionRepository(reopened._connection)
                self.assertEqual(repo.get_run(run.run_id).status, StrategyExecutionStatus.COMPLETED)
            finally:
                reopened.close()

            legacy = os.path.join(tmp, "legacy.sqlite")
            connection = sqlite3.connect(legacy)
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (17);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'strategy_execution_plans'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'strategy_execution_runs'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
