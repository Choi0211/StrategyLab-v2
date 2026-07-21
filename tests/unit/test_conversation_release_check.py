import sqlite3
import tempfile
import unittest
from pathlib import Path

from gaon.runtime.cli import main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
from gaon.runtime.llm_tools import SafeToolExecutor, default_tool_registry
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-21T00:00:00Z"


class ConversationReleaseCheckIdempotencyTests(unittest.TestCase):
    def test_release_check_repeats_three_times_on_one_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "gaon-runtime.sqlite")
            for _ in range(3):
                self.assertEqual(main(["conversation-release-check", "--db", db]), 0)

            connection = sqlite3.connect(db)
            try:
                rows = connection.execute("SELECT message_id FROM conversation_messages ORDER BY message_id").fetchall()
                message_ids = [str(row[0]) for row in rows]
                self.assertEqual(len(message_ids), 6 * 3)
                self.assertEqual(len(set(message_ids)), len(message_ids))
                self.assertTrue(all(message_id.startswith("conversation-release-check:") or message_id.startswith("conversation-assistant:") for message_id in message_ids))
                audits = connection.execute("SELECT tool_name, status FROM llm_tool_audit ORDER BY created_at, audit_id").fetchall()
                self.assertEqual(len(audits), 3 * 3)
                self.assertEqual({str(row[1]) for row in audits}, {"success"})
            finally:
                connection.close()

    def test_release_check_succeeds_after_legacy_fixed_release_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "gaon-runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                brain = LLMConversationBrain(
                    GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
                    store.conversations,
                    tool_executor=SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit),
                )
                brain.respond(LLMConversationRequest("release-check:runtime", "cli", "cli", "가온 상태 알려줘", NOW, "release-check:runtime"))
                legacy_count = store._connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE message_id = 'release-check:runtime'").fetchone()[0]
                self.assertEqual(int(legacy_count), 1)
            finally:
                store.close()

            self.assertEqual(main(["conversation-release-check", "--db", db]), 0)
            self.assertEqual(main(["conversation-release-check", "--db", db]), 0)

            connection = sqlite3.connect(db)
            try:
                legacy_count = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE message_id = 'release-check:runtime'").fetchone()[0]
                self.assertEqual(int(legacy_count), 1)
                namespaced = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE message_id LIKE 'conversation-release-check:%:message:%'").fetchone()[0]
                self.assertEqual(int(namespaced), 6)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO conversation_messages(
                            message_id, session_id, role, content, intent, route, references_json,
                            warnings_json, tool_calls_json, created_at
                        ) SELECT message_id, session_id, role, content, intent, route, references_json,
                                 warnings_json, tool_calls_json, created_at
                            FROM conversation_messages
                           WHERE message_id = 'release-check:runtime'
                        """
                    )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
