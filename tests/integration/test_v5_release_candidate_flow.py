import sqlite3
import tempfile
import unittest

from gaon.adapters.strategy_deployment import FakeStrategyDeploymentAdapter, SQLiteStrategyDeploymentRepository, StrategyDeploymentService, StrategyDeploymentStatus, build_strategy_deployment_request
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.v5_pipeline import GaonV5PipelineOrchestrator, GaonV5PipelineRequest, GaonV5PipelineStage, GaonV5PipelineStatus, SQLiteGaonV5PipelineRepository
from gaon.adapters.champion_registry import SQLiteChampionRegistryRepository


NOW = "2026-07-18T00:00:00Z"


class V5ReleaseCandidateFlowTest(unittest.TestCase):
    def run_pipeline(self, scenario="success", *, approve_promotion=True, approve_deployment=True, adapter=None):
        store = RuntimeStateStore(":memory:")
        orchestrator = GaonV5PipelineOrchestrator(store._connection, adapter=adapter or FakeStrategyDeploymentAdapter(), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
        report = orchestrator.run_demo(GaonV5PipelineRequest(f"v5-{scenario}", f"corr-{scenario}", "actor:redacted", NOW, approve_promotion=approve_promotion, approve_deployment=approve_deployment, scenario=scenario))
        return store, report

    def test_success_pipeline_completes_first_full_system(self) -> None:
        store, report = self.run_pipeline()
        try:
            self.assertEqual(report.status, GaonV5PipelineStatus.COMPLETED)
            self.assertEqual(report.current_stage, GaonV5PipelineStage.COMPLETED)
            self.assertIn("deployment_run_id", report.source_refs)
            self.assertIn("handoff_package_id", report.source_refs)
            self.assertEqual(SQLiteStrategyDeploymentRepository(store._connection).list_runs()[0].status, StrategyDeploymentStatus.SUCCEEDED)
        finally:
            store.close()

    def test_failure_scenarios_stop_before_unsafe_next_stage(self) -> None:
        cases = (
            ("validation_fail", GaonV5PipelineStage.VALIDATION),
            ("keep_champion", GaonV5PipelineStage.CHAMPION_EVALUATION),
            ("promotion_rejected", GaonV5PipelineStage.PROMOTION_APPROVAL),
            ("paper_hold", GaonV5PipelineStage.PAPER_REVALIDATION),
            ("paper_kill", GaonV5PipelineStage.PAPER_REVALIDATION),
        )
        for scenario, stage in cases:
            with self.subTest(scenario=scenario):
                store, report = self.run_pipeline(scenario)
                try:
                    self.assertEqual(report.status, GaonV5PipelineStatus.BLOCKED)
                    self.assertEqual(report.current_stage, stage)
                    self.assertNotIn("deployment_run_id", report.source_refs)
                finally:
                    store.close()

    def test_approval_boundaries_are_preserved_and_resumable(self) -> None:
        store, report = self.run_pipeline(approve_promotion=False, approve_deployment=True)
        try:
            self.assertEqual(report.status, GaonV5PipelineStatus.WAITING_FOR_APPROVAL)
            self.assertEqual(report.current_stage, GaonV5PipelineStage.PROMOTION_APPROVAL)
            resumed = GaonV5PipelineOrchestrator(store._connection, event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).run_demo(GaonV5PipelineRequest("v5-success", "corr-success", "actor:redacted", NOW, approve_promotion=False, approve_deployment=True))
            self.assertEqual(resumed.status, GaonV5PipelineStatus.WAITING_FOR_APPROVAL)
            self.assertNotIn("champion_version_id", resumed.source_refs)
        finally:
            store.close()

        store, report = self.run_pipeline(approve_promotion=True, approve_deployment=False)
        try:
            self.assertEqual(report.status, GaonV5PipelineStatus.WAITING_FOR_APPROVAL)
            self.assertEqual(report.current_stage, GaonV5PipelineStage.DEPLOYMENT_APPROVAL)
            self.assertNotIn("deployment_run_id", report.source_refs)
        finally:
            store.close()

    def test_deployment_integrity_failure_paths(self) -> None:
        store, report = self.run_pipeline(approve_promotion=True, approve_deployment=False)
        try:
            package_id = report.source_refs["handoff_package_id"]
            service = StrategyDeploymentService(SQLiteStrategyDeploymentRepository(store._connection), SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), FakeStrategyDeploymentAdapter(), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            blocked = service.plan(build_strategy_deployment_request("v5-unapproved", package_id=package_id, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(blocked.status, StrategyDeploymentStatus.BLOCKED)
        finally:
            store.close()

        store, report = self.run_pipeline()
        try:
            package_id = report.source_refs["handoff_package_id"]
            store._connection.execute("UPDATE strategy_handoff_approvals SET package_checksum = 'stale'")
            service = StrategyDeploymentService(SQLiteStrategyDeploymentRepository(store._connection), SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), FakeStrategyDeploymentAdapter(), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            plan = service.plan(build_strategy_deployment_request("v5-checksum", package_id=package_id, actor_ref="actor:redacted", requested_at=NOW))
            self.assertEqual(plan.status, StrategyDeploymentStatus.BLOCKED)
        finally:
            store.close()

        for adapter, expected in (
            (FakeStrategyDeploymentAdapter(fail_health=True), StrategyDeploymentStatus.BLOCKED),
            (FakeStrategyDeploymentAdapter(fail_verify=True), StrategyDeploymentStatus.ROLLED_BACK),
            (FakeStrategyDeploymentAdapter(fail_verify=True, fail_rollback=True), StrategyDeploymentStatus.ROLLBACK_FAILED),
        ):
            with self.subTest(expected=expected):
                store, report = self.run_pipeline(adapter=adapter)
                try:
                    self.assertEqual(SQLiteStrategyDeploymentRepository(store._connection).list_runs()[0].status, expected)
                finally:
                    store.close()

    def test_pipeline_persistence_and_v21_migration(self) -> None:
        store, report = self.run_pipeline()
        try:
            loaded = SQLiteGaonV5PipelineRepository(store._connection).get_run(report.run_id)
            self.assertEqual(loaded.status, GaonV5PipelineStatus.COMPLETED)
        finally:
            store.close()

        with tempfile.TemporaryDirectory() as tmp:
            connection = sqlite3.connect(f"{tmp}/legacy.sqlite")
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (20);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'gaon_v5_pipeline_runs'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
