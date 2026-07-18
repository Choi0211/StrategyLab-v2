import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.research.knowledge import KnowledgeProposalStatus, SQLiteKnowledgeProposalRepository
from gaon.runtime.cli import main as cli_main
from gaon.runtime.daily_research import DailyResearchPipeline, DailyResearchProfile, DailyResearchRepository, DailyResearchRunStatus
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class DailyResearchFlowTest(unittest.TestCase):
    def test_durable_profile_schedule_run_report_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                daily_repo = DailyResearchRepository(store._connection)
                scheduled_repo = ScheduledJobRepository(store._connection)
                profile = DailyResearchProfile("daily-korea", "Korea market", "KOSPI daily risk", True, 80, ("fake",), "daily", "ko-KR", NOW, NOW)
                daily_repo.create_profile(profile)
                pipeline = DailyResearchPipeline(daily_repo, scheduled_repo, GaonRuntimeConfig())
                pipeline.schedule_profile(profile, next_run_at=NOW)
                runs = pipeline.run_due(now=NOW)

                self.assertEqual(runs[0].status, DailyResearchRunStatus.COMPLETED)
                self.assertIsNotNone(runs[0].result)
                assert runs[0].result is not None
                self.assertIn("Evidence and Citations", runs[0].result.to_markdown())
                proposal = SQLiteKnowledgeProposalRepository(store._connection).get(runs[0].proposal_ids[0])
                self.assertEqual(proposal.status, KnowledgeProposalStatus.PENDING_REVIEW)
            finally:
                store.close()

            reopened = RuntimeStateStore(db)
            try:
                runs = DailyResearchRepository(reopened._connection).list_runs("daily-korea")
                self.assertEqual(len(runs), 1)
                self.assertIsNotNone(runs[0].result)
            finally:
                reopened.close()

    def test_cli_daily_research_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    cli_main(
                        [
                            "daily-research-create",
                            "--db",
                            db,
                            "--profile-id",
                            "cli-profile",
                            "--topic",
                            "CLI topic",
                            "--query",
                            "CLI daily research",
                            "--next-run-at",
                            NOW,
                        ]
                    ),
                    0,
                )
            self.assertIn("daily-research-create", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["daily-research-list", "--db", db]), 0)
            self.assertIn("cli-profile", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["daily-research-run", "--db", db, "--due", "--now", NOW]), 0)
            self.assertIn("status=completed", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["daily-research-report", "--db", db, "cli-profile", "--format", "markdown"]), 0)
            self.assertIn("# Daily Research: CLI topic", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["daily-research-report", "--db", db, "cli-profile", "--format", "json"]), 0)
            self.assertIn('"topic":"CLI topic"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
