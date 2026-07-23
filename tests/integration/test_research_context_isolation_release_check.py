import tempfile
import unittest
from pathlib import Path

from gaon.runtime.cli import main
from gaon.runtime.storage import RuntimeStateStore


class ResearchContextIsolationReleaseCheckTests(unittest.TestCase):
    def test_context_isolation_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = str(Path(temp_dir) / "runtime.sqlite")
            for _ in range(3):
                self.assertEqual(main(["research-context-isolation-release-check", "--db", db]), 0)
            store = RuntimeStateStore(db)
            try:
                messages = store._connection.execute(
                    "SELECT message_id FROM conversation_messages WHERE message_id LIKE 'research-context-isolation-release-check:%'"
                ).fetchall()
                self.assertEqual(len(messages), len({row[0] for row in messages}))
                self.assertGreaterEqual(store.status().schema_version, 32)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
