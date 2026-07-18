import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.executive_planner import AgentSelection, ToolSelection
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledAutomationRunner, ScheduledJob, ScheduledJobRepository, ScheduledRunStatus
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ScheduledAutomationFlowTest(unittest.TestCase):
    def test_scheduled_job_to_planner_dispatcher_agent_result_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            repo = ScheduledJobRepository(store._connection)
            repo.create(
                ScheduledJob(
                    "job-1",
                    "Research",
                    "research evidence",
                    ScheduleDefinition("UTC", NOW),
                    True,
                    NOW,
                    NOW,
                    agent_selection=AgentSelection.RESEARCH_BRAIN,
                    tool_constraints=(ToolSelection.RESEARCH_PLANNER,),
                )
            )
            runs = ScheduledAutomationRunner(repo, GaonRuntimeConfig()).run_due(now=NOW)
            store.close()

            restored = RuntimeStateStore(db)
            restored_repo = ScheduledJobRepository(restored._connection)
            self.assertEqual(runs[0].status, ScheduledRunStatus.SUCCEEDED)
            self.assertEqual(restored_repo.get("job-1").enabled, False)
            self.assertEqual(restored_repo.list_runs("job-1")[0].result["agent_name"], "research_brain")
            restored.close()

    def test_failed_disabled_and_approval_blocked_flows(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repo = ScheduledJobRepository(store._connection)
            repo.create(ScheduledJob("disabled", "Disabled", "research evidence", ScheduleDefinition("UTC", NOW), False, NOW, NOW))
            repo.create(ScheduledJob("approval", "Approval", "research evidence", ScheduleDefinition("UTC", NOW), True, NOW, NOW, approval_required=True))
            repo.create(ScheduledJob("failed", "Failed", "runtime status", ScheduleDefinition("UTC", NOW), True, NOW, NOW, max_attempts=1))

            runs = ScheduledAutomationRunner(repo, GaonRuntimeConfig()).run_due(now=NOW)
            by_job = {run.job_id: run.status for run in runs}

            self.assertNotIn("disabled", by_job)
            self.assertEqual(by_job["approval"], ScheduledRunStatus.BLOCKED)
            self.assertEqual(by_job["failed"], ScheduledRunStatus.FAILED)
        finally:
            store.close()

    def test_cli_schedule_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    cli_main(
                        [
                            "schedule-create",
                            "--db",
                            db,
                            "--job-id",
                            "job-cli",
                            "--name",
                            "CLI",
                            "--request",
                            "research evidence",
                            "--next-run-at",
                            NOW,
                            "--agent",
                            "research",
                        ]
                    ),
                    0,
                )
                self.assertEqual(cli_main(["schedule-list", "--db", db]), 0)
                self.assertEqual(cli_main(["schedule-show", "--db", db, "job-cli"]), 0)
                self.assertEqual(cli_main(["schedule-disable", "--db", db, "job-cli"]), 0)
                self.assertEqual(cli_main(["schedule-enable", "--db", db, "job-cli"]), 0)
                self.assertEqual(cli_main(["schedule-run-due", "--db", db, "--now", NOW]), 0)

            text = output.getvalue()
            self.assertIn("schedule-create: job_id=job-cli", text)
            self.assertIn("schedule-run-due: run_id=scheduled-run:job-cli", text)


if __name__ == "__main__":
    unittest.main()
