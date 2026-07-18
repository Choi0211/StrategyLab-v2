import os
import sqlite3
import tempfile
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, ToolSelection
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.scheduled_automation import (
    ScheduleDefinition,
    ScheduledAutomationRunner,
    ScheduledJob,
    ScheduledJobRepository,
    ScheduledRunStatus,
    record_scheduled_job_metric,
)
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ScheduledAutomationTest(unittest.TestCase):
    def job(
        self,
        job_id: str = "job-1",
        *,
        request: str = "research evidence",
        enabled: bool = True,
        approval_required: bool = False,
        agent_selection: AgentSelection | None = AgentSelection.RESEARCH_BRAIN,
        tool_constraints: tuple[ToolSelection, ...] = (ToolSelection.RESEARCH_PLANNER,),
        max_attempts: int = 2,
    ) -> ScheduledJob:
        return ScheduledJob(
            job_id,
            "Research fixture",
            request,
            ScheduleDefinition("UTC", NOW),
            enabled,
            NOW,
            NOW,
            approval_required=approval_required,
            agent_selection=agent_selection,
            tool_constraints=tool_constraints,
            max_attempts=max_attempts,
        )

    def test_create_duplicate_enable_disable_and_deterministic_listing(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job("job-b"))
            repo.create(self.job("job-a"))

            self.assertEqual(tuple(job.job_id for job in repo.list()), ("job-a", "job-b"))
            with self.assertRaises(ValueError):
                repo.create(self.job("job-a"))
            self.assertFalse(repo.set_enabled("job-a", False, updated_at=NOW).enabled)
            self.assertTrue(repo.set_enabled("job-a", True, updated_at=NOW).enabled)
        finally:
            store.close()

    def test_due_detection_disabled_skip_success_events_metrics_and_duplicate_run_protection(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job("job-1"))
            repo.create(self.job("disabled", enabled=False))
            event_store = SQLiteEventStore(store._connection)
            runner = ScheduledAutomationRunner(repo, GaonRuntimeConfig(), metrics=metrics, event_store=event_store)

            runs = runner.run_due(now=NOW)
            second = runner.run_due(now=NOW)
            events = event_store.read_after()

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, ScheduledRunStatus.SUCCEEDED)
            self.assertEqual(second, ())
            self.assertEqual(tuple(run.job_id for run in repo.list_runs()), ("job-1",))
            self.assertIn("ScheduledExecutionStarted", {event.event_type for event in events})
            self.assertIn("ScheduledExecutionCompleted", {event.event_type for event in events})
            self.assertIn("gaon_scheduled_executions_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_approval_required_blocks_before_agent_execution(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job("approval", approval_required=True))
            runs = ScheduledAutomationRunner(repo, GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection)).run_due(now=NOW)
            events = SQLiteEventStore(store._connection).read_after()

            self.assertEqual(runs[0].status, ScheduledRunStatus.BLOCKED)
            self.assertIn("approval", runs[0].result["reason"])
            self.assertIn("ScheduledExecutionBlocked", {event.event_type for event in events})
        finally:
            store.close()

    def test_failure_isolated_bounded_retry_and_no_same_timestamp_overlap(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job("runtime", request="runtime status", agent_selection=None, tool_constraints=(), max_attempts=2))
            runner = ScheduledAutomationRunner(repo, GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection))

            first = runner.run_due(now=NOW)
            duplicate = runner.run_due(now=NOW)
            second = runner.run_due(now="2026-07-18T00:00:01Z")
            third = runner.run_due(now="2026-07-18T00:00:02Z")

            self.assertEqual(first[0].status, ScheduledRunStatus.FAILED)
            self.assertEqual(duplicate, ())
            self.assertEqual(second[0].status, ScheduledRunStatus.FAILED)
            self.assertEqual(third, ())
            self.assertFalse(repo.get("runtime").enabled)
        finally:
            store.close()

    def test_constraint_mismatch_blocks_without_dispatching_wrong_agent(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job("mismatch", request="memory lookup", agent_selection=AgentSelection.RESEARCH_BRAIN, tool_constraints=()))
            runs = ScheduledAutomationRunner(repo, GaonRuntimeConfig()).run_due(now=NOW)

            self.assertEqual(runs[0].status, ScheduledRunStatus.BLOCKED)
            self.assertIn("constraint", runs[0].result["reason"])
        finally:
            store.close()

    def test_free_only_defaults_and_job_metric(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(self.job())
            self.assertTrue(GaonRuntimeConfig().free_only_mode)
            record_scheduled_job_metric(metrics, repo)
            self.assertIn("gaon_scheduled_jobs_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_schema_v8_migrates_to_v9(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (8);
                """
            )
            migrate(connection)
            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'scheduled_automation_jobs'").fetchone()
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIsNotNone(table)
            connection.close()


if __name__ == "__main__":
    unittest.main()
