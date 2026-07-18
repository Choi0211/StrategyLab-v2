import os
import sqlite3
import tempfile
import unittest

from gaon.research.knowledge import KnowledgeProposalStatus, SQLiteKnowledgeProposalRepository
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.daily_research import DailyResearchPipeline, DailyResearchProfile, DailyResearchRepository, DailyResearchRunStatus, record_daily_research_profile_metric
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.scheduled_automation import ScheduledJobRepository, ScheduledRunStatus
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class DailyResearchTest(unittest.TestCase):
    def profile(self, profile_id: str = "p1", *, enabled: bool = True, priority: int = 50, query: str = "KOSPI momentum") -> DailyResearchProfile:
        return DailyResearchProfile(
            profile_id,
            "Korea market",
            query,
            enabled,
            priority,
            ("fake",),
            "daily",
            "ko-KR",
            NOW,
            NOW,
            {"suite": "unit"},
        )

    def test_profile_create_duplicate_enable_disable_order_and_metrics(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = DailyResearchRepository(store._connection)
            repo.create_profile(self.profile("low", priority=10))
            repo.create_profile(self.profile("high", priority=90))

            self.assertEqual(tuple(profile.profile_id for profile in repo.list_profiles()), ("high", "low"))
            with self.assertRaises(ValueError):
                repo.create_profile(self.profile("high"))
            self.assertFalse(repo.set_enabled("high", False, updated_at=NOW).enabled)
            self.assertTrue(repo.set_enabled("high", True, updated_at=NOW).enabled)
            record_daily_research_profile_metric(metrics, repo)
            self.assertIn("gaon_daily_research_profiles_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_schedule_profile_uses_sprint38_scheduler_contract(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            daily_repo = DailyResearchRepository(store._connection)
            scheduled_repo = ScheduledJobRepository(store._connection)
            profile = self.profile()
            daily_repo.create_profile(profile)

            DailyResearchPipeline(daily_repo, scheduled_repo, GaonRuntimeConfig()).schedule_profile(profile, next_run_at=NOW)
            job = scheduled_repo.get("daily-research:p1")

            self.assertEqual(job.metadata["kind"], "daily_research")
            self.assertEqual(job.metadata["profile_id"], "p1")
            self.assertTrue(job.enabled)
        finally:
            store.close()

    def test_due_execution_builds_bounded_report_events_metrics_and_pending_proposal(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            daily_repo = DailyResearchRepository(store._connection)
            scheduled_repo = ScheduledJobRepository(store._connection)
            profile = self.profile()
            daily_repo.create_profile(profile)
            event_store = SQLiteEventStore(store._connection)
            pipeline = DailyResearchPipeline(daily_repo, scheduled_repo, GaonRuntimeConfig(), metrics=metrics, event_store=event_store)
            pipeline.schedule_profile(profile, next_run_at=NOW)

            runs = pipeline.run_due(now=NOW)
            scheduled_runs = scheduled_repo.list_runs("daily-research:p1")
            events = {event.event_type for event in event_store.read_after()}

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, DailyResearchRunStatus.COMPLETED)
            self.assertEqual(scheduled_runs[0].status, ScheduledRunStatus.SUCCEEDED)
            self.assertIsNotNone(runs[0].result)
            assert runs[0].result is not None
            self.assertLessEqual(len(runs[0].result.citations), 3)
            self.assertIn("mode", runs[0].result.provider_metadata)
            self.assertEqual(runs[0].result.provider_metadata["proposal_status"], "pending_review")
            proposal = SQLiteKnowledgeProposalRepository(store._connection).get(runs[0].proposal_ids[0])
            self.assertEqual(proposal.status, KnowledgeProposalStatus.PENDING_REVIEW)
            self.assertIn("DailyResearchRunStarted", events)
            self.assertIn("DailyResearchRunCompleted", events)
            self.assertIn("gaon_daily_research_runs_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_disabled_profile_is_not_executed(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = DailyResearchRepository(store._connection)
            scheduled_repo = ScheduledJobRepository(store._connection)
            profile = self.profile(enabled=False)
            repo.create_profile(profile)
            pipeline = DailyResearchPipeline(repo, scheduled_repo, GaonRuntimeConfig())
            run = pipeline.run_profile("p1", now=NOW)

            self.assertEqual(run.status, DailyResearchRunStatus.SKIPPED)
            self.assertIsNone(run.result)
        finally:
            store.close()

    def test_duplicate_run_protection_and_failure_isolation(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = DailyResearchRepository(store._connection)
            scheduled_repo = ScheduledJobRepository(store._connection)
            repo.create_profile(self.profile("ok"))
            repo.create_profile(self.profile("failure", query="fail research"))
            pipeline = DailyResearchPipeline(repo, scheduled_repo, GaonRuntimeConfig())

            first = pipeline.run_profile("ok", now=NOW)
            duplicate = pipeline.run_profile("ok", now=NOW)
            failed = pipeline.run_profile("failure", now=NOW)

            self.assertEqual(first.run_id, duplicate.run_id)
            self.assertEqual(len(repo.list_runs("ok")), 1)
            self.assertEqual(failed.status, DailyResearchRunStatus.FAILED)
            self.assertEqual(failed.error, "RuntimeError")
        finally:
            store.close()

    def test_schema_v9_migrates_to_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (9);
                """
            )
            migrate(connection)
            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            profile_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'daily_research_profiles'").fetchone()
            run_table = connection.execute("SELECT name FROM sqlite_master WHERE name = 'daily_research_runs'").fetchone()

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIsNotNone(profile_table)
            self.assertIsNotNone(run_table)
            connection.close()


if __name__ == "__main__":
    unittest.main()
