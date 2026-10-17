from __future__ import annotations

from datetime import UTC, datetime, timedelta
import gzip
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gaon.runtime.migrations import migrate
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.storage_maintenance import (
    StorageMaintenanceRuntimeService,
    perform_storage_maintenance,
)

NOW = "2026-10-18T00:00:00Z"


def _old(path: Path, days: int) -> None:
    ts = (datetime(2026, 10, 18, tzinfo=UTC) - timedelta(days=days)).timestamp()
    os.utime(path, (ts, ts))


class StorageMaintenanceSafetyTests(unittest.TestCase):
    def test_only_explicit_regenerable_artifacts_are_touched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            repo = root / "repo"
            state.mkdir(); repo.mkdir()
            (repo / ".cache" / "pip").mkdir(parents=True)

            live_db = state / "gaon-runtime.sqlite"
            live_db.write_bytes(b"LIVE-DB-MUST-STAY")
            evidence = state / "research_evidence"
            evidence.mkdir()
            evidence_file = evidence / "evidence.json"
            evidence_file.write_text("important evidence", encoding="utf-8")
            research_inputs = state / "research_inputs"
            research_inputs.mkdir()
            input_file = research_inputs / "source.txt"
            input_file.write_text("user research input", encoding="utf-8")

            backup = state / "gaon-runtime-pre-fix-20260901.sqlite"
            backup_payload = (b"backup-data-" * 1000)
            backup.write_bytes(backup_payload)
            _old(backup, 20)

            smoke = state / "dev_repo_smoke-old.git"
            smoke.mkdir()
            (smoke / "junk").write_bytes(b"junk")
            _old(smoke, 10)

            pip_file = repo / ".cache" / "pip" / "old.whl"
            pip_file.write_bytes(b"cache")
            _old(pip_file, 40)

            with patch("gaon.runtime.storage_maintenance.subprocess.run") as run:
                run.return_value.returncode = 0
                result = perform_storage_maintenance(state_root=state, repo_root=repo, now=NOW)

            self.assertEqual(live_db.read_bytes(), b"LIVE-DB-MUST-STAY")
            self.assertEqual(evidence_file.read_text(encoding="utf-8"), "important evidence")
            self.assertEqual(input_file.read_text(encoding="utf-8"), "user research input")
            self.assertFalse(backup.exists())
            compressed = Path(str(backup) + ".gz")
            self.assertTrue(compressed.is_file())
            with gzip.open(compressed, "rb") as handle:
                self.assertEqual(handle.read(), backup_payload)
            self.assertFalse(smoke.exists())
            self.assertFalse(pip_file.exists())
            self.assertFalse(result.to_json()["live_database_touched"])
            self.assertFalse(result.to_json()["research_evidence_touched"])
            self.assertGreater(result.reclaimed_bytes, 0)

    def test_recent_backups_and_smoke_artifacts_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"; repo = root / "repo"
            state.mkdir(); repo.mkdir()
            backup = state / "gaon-runtime-pre-fix-20261017.sqlite"
            backup.write_bytes(b"recent")
            smoke = state / "dev_worktrees_smoke-recent"
            smoke.mkdir(); (smoke / "x").write_text("x")
            with patch("gaon.runtime.storage_maintenance.subprocess.run") as run:
                run.return_value.returncode = 0
                perform_storage_maintenance(state_root=state, repo_root=repo, now=NOW)
            self.assertTrue(backup.exists())
            self.assertTrue(smoke.exists())


class StorageMaintenanceRuntimeTests(unittest.TestCase):
    def test_daily_job_runs_once_per_utc_day(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        repo = ScheduledJobRepository(connection)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / "state"; code = root / "repo"
            state.mkdir(); code.mkdir()
            with patch("gaon.runtime.storage_maintenance.subprocess.run") as run:
                run.return_value.returncode = 0
                service = StorageMaintenanceRuntimeService(
                    repo, now_factory=lambda: NOW, state_root=state, repo_root=code
                )
                first = service.tick()
                second = service.tick()
        self.assertTrue(first.jobs_registered)
        self.assertEqual(len(first.results), 1)
        self.assertFalse(second.jobs_registered)
        self.assertEqual(len(second.results), 0)
        runs = [r for r in repo.list_runs() if r.job_id.startswith("gaon-storage-maintenance:")]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status.value, "succeeded")


if __name__ == "__main__":
    unittest.main()
