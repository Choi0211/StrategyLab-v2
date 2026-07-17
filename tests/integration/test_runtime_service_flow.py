import os
import tempfile
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore


class RuntimeServiceFlowTest(unittest.TestCase):
    def test_restart_recovery_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            store.save_offset("100", 99, "2026-07-17T00:00:00Z")
            self.assertTrue(GaonRuntimeService(GaonRuntimeConfig(), store).start().running)
            store.close()

            restored = RuntimeStateStore(db)
            self.assertEqual(restored.get_offset("100"), 99)
            self.assertTrue(GaonRuntimeService(GaonRuntimeConfig(), restored).start().running)
            restored.close()


if __name__ == "__main__":
    unittest.main()
