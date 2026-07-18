import sqlite3
import tempfile
import unittest

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, RollbackRecommendation, SQLitePaperRevalidationRepository
from gaon.adapters.strategy_deployment import FakeStrategyDeploymentAdapter, SQLiteStrategyDeploymentRepository, StrategyDeploymentService, StrategyDeploymentStatus, build_strategy_deployment_request
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, build_strategy_handoff_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyDeploymentTest(unittest.TestCase):
    def seed(self, *, approve=True):
        store = RuntimeStateStore(":memory:")
        backtests = SQLiteBacktestRepository(store._connection)
        request = build_backtest_request("deploy-bt", "turtle_v5", "kospi_fixture", "2025-01-01", "2025-12-31", actor_ref="actor:redacted", created_at=NOW, parameters={"lookback": 20, "risk_pct": 0.02})
        result = BacktestExecutionService(FakeBacktestAdapter(), repository=backtests).run(request, BacktestExecutionContext(30, 64000, NOW))
        active = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint=result.fingerprint, backtest_id=result.result_id, actor_ref="actor:redacted", activated_at=NOW)
        SQLitePaperRevalidationRepository(store._connection).add_report(PaperRevalidationReport("rv-live", PaperRevalidationStatus.LIVE_ELIGIBLE, "paper_revalidation_policy_v1", "paper-session-1", active.active_version_id, active.fingerprint, (), (), (), RollbackRecommendation(False, "not recommended"), NOW))
        handoff = StrategyHandoffService(SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), SQLitePaperRevalidationRepository(store._connection), SQLiteBacktestRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
        package = handoff.create(build_strategy_handoff_request("handoff-req", revalidation_id="rv-live", actor_ref="actor:redacted", requested_at=NOW))
        if approve:
            package = handoff.approve(package.package_id, approver_ref="actor:redacted", decided_at=NOW)
        return store, package

    def service(self, store, adapter, metrics=None):
        return StrategyDeploymentService(SQLiteStrategyDeploymentRepository(store._connection), SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), adapter, event_store=SQLiteEventStore(store._connection), metrics=metrics)

    def test_unapproved_checksum_mismatch_and_incompatible_packages_are_blocked(self) -> None:
        store, package = self.seed(approve=False)
        try:
            plan = self.service(store, FakeStrategyDeploymentAdapter()).plan(build_strategy_deployment_request("deploy-unapproved", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(plan.status, StrategyDeploymentStatus.BLOCKED)
            self.assertIn("not approved", plan.reason)
        finally:
            store.close()

        store, package = self.seed()
        try:
            store._connection.execute("UPDATE strategy_handoff_approvals SET package_checksum = 'stale'")
            plan = self.service(store, FakeStrategyDeploymentAdapter()).plan(build_strategy_deployment_request("deploy-stale", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(plan.status, StrategyDeploymentStatus.BLOCKED)
            self.assertIn("checksum", plan.reason)
        finally:
            store.close()

        store, package = self.seed()
        try:
            plan = self.service(store, FakeStrategyDeploymentAdapter(fail_validate=True)).plan(build_strategy_deployment_request("deploy-incompat", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(plan.status, StrategyDeploymentStatus.BLOCKED)
            self.assertIn("compatibility", plan.reason)
        finally:
            store.close()

    def test_backup_dry_run_apply_verify_and_duplicate_prevention(self) -> None:
        store, package = self.seed()
        adapter = FakeStrategyDeploymentAdapter()
        metrics = MetricsCollector()
        try:
            service = self.service(store, adapter, metrics=metrics)
            plan = service.plan(build_strategy_deployment_request("deploy-ok", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            run = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            duplicate = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            self.assertEqual(plan.status, StrategyDeploymentStatus.PREFLIGHT_PASSED)
            self.assertTrue(adapter.dry_run_called)
            self.assertEqual(run.status, StrategyDeploymentStatus.SUCCEEDED)
            self.assertEqual(duplicate.status, StrategyDeploymentStatus.BLOCKED)
            self.assertEqual(len(SQLiteStrategyDeploymentRepository(store._connection).list_backups()), 1)
            self.assertIn("gaon_strategy_deployments_succeeded_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_dry_run_failure_blocks_before_apply(self) -> None:
        store, package = self.seed()
        adapter = FakeStrategyDeploymentAdapter(fail_dry_run=True)
        try:
            service = self.service(store, adapter)
            plan = service.plan(build_strategy_deployment_request("deploy-dry-run", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            run = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            self.assertEqual(run.status, StrategyDeploymentStatus.FAILED)
            self.assertFalse(adapter.applied)
        finally:
            store.close()

    def test_restart_health_verify_failure_rolls_back_and_rollback_failure_surfaces(self) -> None:
        for kwargs, expected in (
            ({"fail_restart": True}, StrategyDeploymentStatus.ROLLED_BACK),
            ({"fail_health": True}, StrategyDeploymentStatus.BLOCKED),
            ({"fail_verify": True}, StrategyDeploymentStatus.ROLLED_BACK),
            ({"fail_verify": True, "fail_rollback": True}, StrategyDeploymentStatus.ROLLBACK_FAILED),
        ):
            with self.subTest(kwargs=kwargs):
                store, package = self.seed()
                try:
                    service = self.service(store, FakeStrategyDeploymentAdapter(**kwargs))
                    plan = service.plan(build_strategy_deployment_request(f"deploy-{len(kwargs)}-{expected.value}", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
                    run = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
                    if plan.status == StrategyDeploymentStatus.BLOCKED:
                        self.assertEqual(run.status, StrategyDeploymentStatus.BLOCKED)
                    else:
                        self.assertEqual(run.status, expected)
                finally:
                    store.close()

    def test_events_persistence_and_v20_migration(self) -> None:
        store, package = self.seed()
        try:
            service = self.service(store, FakeStrategyDeploymentAdapter())
            plan = service.plan(build_strategy_deployment_request("deploy-events", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            events = {event.event_type for event in SQLiteEventStore(store._connection).read_after()}
            self.assertIn("StrategyDeploymentSucceeded", events)
            self.assertEqual(len(SQLiteStrategyDeploymentRepository(store._connection).list_runs()), 1)
        finally:
            store.close()

        with tempfile.TemporaryDirectory() as tmp:
            connection = sqlite3.connect(f"{tmp}/legacy.sqlite")
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (19);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'strategy_deployment_runs'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
