"""Unit tests for gaon.adapters.mymoneyguard.MyMoneyGuardSnapshotReader -
pure read-only parsing of an already-sanitized snapshot file. Never
touches /root/MyMoneyGuard, never calls KIS, never writes anything.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from gaon.adapters.mymoneyguard import MyMoneyGuardSnapshotReader


class MyMoneyGuardSnapshotReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "snapshot.json")

    def _write(self, payload: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_missing_file_is_reported_honestly(self) -> None:
        result = MyMoneyGuardSnapshotReader(path=self.path).read()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "snapshot_not_found")

    def test_malformed_json_is_reported_honestly_not_raised(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        result = MyMoneyGuardSnapshotReader(path=self.path).read()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "snapshot_unreadable")

    def test_non_object_json_is_reported_honestly(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        result = MyMoneyGuardSnapshotReader(path=self.path).read()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "snapshot_invalid_format")

    def test_fresh_snapshot_is_available_and_not_stale(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        self._write({"generated_at_utc": now.isoformat(), "markets": {"KR": {"auto_trade_enabled": True}}})
        result = MyMoneyGuardSnapshotReader(path=self.path).read(now=now)
        self.assertTrue(result["available"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["markets"]["KR"]["auto_trade_enabled"], True)
        self.assertFalse(result["order_execution_connected"])
        self.assertTrue(result["read_only"])

    def test_old_snapshot_is_marked_stale_not_hidden(self) -> None:
        generated = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)  # 3h later
        self._write({"generated_at_utc": generated.isoformat(), "markets": {}})
        result = MyMoneyGuardSnapshotReader(path=self.path).read(now=now)
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])

    def test_missing_generated_at_is_treated_as_stale(self) -> None:
        self._write({"markets": {}})
        result = MyMoneyGuardSnapshotReader(path=self.path).read()
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])

    def test_default_path_resolves_env_var_at_read_time_not_def_time(self) -> None:
        os.environ["MYMONEYGUARD_SNAPSHOT_PATH"] = self.path
        try:
            self._write({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "markets": {}})
            result = MyMoneyGuardSnapshotReader().read()
            self.assertTrue(result["available"])
        finally:
            del os.environ["MYMONEYGUARD_SNAPSHOT_PATH"]


if __name__ == "__main__":
    unittest.main()
