import sqlite3
import unittest

from gaon.runtime.migrations import migrate
from gaon.runtime.autonomous_research_runtime import ensure_autonomous_research_job
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.research_ops_audit import audit


class ResearchOpsAuditTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.repo = ScheduledJobRepository(self.connection)

    def test_missing_schedule_and_high_disk(self):
        result = audit(self.connection, now="2026-10-25T12:00:00Z", disk_used_percent=84)
        self.assertIn("research_scheduler_missing", result["warnings"])
        self.assertIn("disk_usage_high", result["warnings"])
        self.assertTrue(result["read_only"])

    def test_fresh_job_has_no_scheduler_warning(self):
        ensure_autonomous_research_job(self.repo, now="2026-10-25T12:00:00Z")
        result = audit(self.connection, now="2026-10-25T12:00:00Z", disk_used_percent=50)
        self.assertNotIn("research_scheduler_overdue", result["warnings"])

    def test_overdue_job_detected(self):
        ensure_autonomous_research_job(self.repo, now="2026-10-24T00:00:00Z")
        result = audit(self.connection, now="2026-10-25T12:00:00Z", disk_used_percent=50)
        self.assertIn("research_scheduler_overdue", result["warnings"])

    def test_stale_claim_detected_without_mutation(self):
        ensure_autonomous_research_job(self.repo, now="2026-10-24T00:00:00Z")
        job = next(j for j in self.repo.list() if j.enabled)
        self.repo.claim_run(job, now="2026-10-24T00:00:00Z")
        result = audit(self.connection, now="2026-10-25T12:00:00Z", disk_used_percent=50)
        self.assertIn("research_run_stale", result["warnings"])
        self.assertEqual(len(self.repo.list_runs(job.job_id)), 1)


if __name__ == "__main__":
    unittest.main()
