from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gaon.storage.foundation import (
    DIRECTORIES,
    GaonStorage,
    resolve_data_root,
)


class GaonStorageFoundationTests(unittest.TestCase):
    def test_env_root_has_priority(self) -> None:
        root = resolve_data_root(
            {"GAON_DATA_ROOT": "/tmp/custom-gaon"},
            system="Linux",
        )
        self.assertEqual(root, Path("/tmp/custom-gaon"))

    def test_linux_default(self) -> None:
        root = resolve_data_root({}, system="Linux")
        self.assertEqual(root, Path("/var/lib/strategylab/gaon-data"))

    def test_windows_default_contract(self) -> None:
        root = resolve_data_root({}, system="Windows")
        self.assertEqual(str(root), r"D:\Gaon")

    def test_initialize_builds_complete_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = GaonStorage(Path(tmp) / "Gaon")
            status = storage.initialize()

            self.assertTrue(status.exists)
            self.assertTrue(status.writable)
            self.assertEqual(status.directory_count, len(DIRECTORIES))
            self.assertTrue((storage.root / ".gaon-storage.json").is_file())

    def test_release_check_preserves_safety_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = GaonStorage(Path(tmp) / "Gaon")
            payload = storage.release_check()

            self.assertEqual(payload["safety"], "pass")
            self.assertTrue(payload["checks"]["automatic_trading_disabled"])
            self.assertTrue(
                payload["checks"]["automatic_champion_promotion_disabled"]
            )
            self.assertTrue(
                payload["checks"]["external_content_is_evidence"]
            )


if __name__ == "__main__":
    unittest.main()
