import tempfile
import unittest
from pathlib import Path

from gaon.runtime.cli import main
from gaon.runtime.storage import RuntimeStateStore


class ResearchGroundingReleaseCheckTests(unittest.TestCase):
    def test_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = str(Path(temp_dir) / "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                initial_schema = store.status().schema_version
            finally:
                store.close()
            for _ in range(3):
                self.assertEqual(main(["research-grounding-release-check", "--db", db]), 0)
            store = RuntimeStateStore(db)
            try:
                self.assertEqual(store.status().schema_version, initial_schema)
                messages = store._connection.execute(
                    "SELECT message_id FROM conversation_messages WHERE message_id LIKE 'research-grounding-release-check:%'"
                ).fetchall()
                self.assertEqual(len(messages), len({row[0] for row in messages}))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
