import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.storage import RuntimeStateStore


class LLMBrainHardeningTests(unittest.TestCase):
    def test_cli_release_check_and_registry_are_read_only(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["conversation-release-check"]), 0)
        self.assertIn("PASS", output.getvalue())

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["tool-registry-show"]), 0)
        self.assertIn("runtime_status", output.getvalue())

    def test_cli_conversation_status_reads_persistent_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                LLMConversationBrain(GaonRuntimeConfig(), store.conversations).respond(
                    LLMConversationRequest("telegram:100", "telegram-user:200", "telegram", "안녕", "2026-07-19T00:00:00Z", "m1")
                )
            finally:
                store.close()

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["conversation-status", "--db", db]), 0)
            self.assertIn("session_id=telegram:100", output.getvalue())
            self.assertIn("messages=2", output.getvalue())

    def test_tool_audit_history_cli_redacts_and_reports_denials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit).execute(
                    ToolRequest("runtime_status", {"api_key": "secret"}, "test", "2026-07-19T00:00:00Z")
                )
            finally:
                store.close()

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["tool-audit-history", "--db", db]), 0)
            self.assertIn("status=denied", output.getvalue())

    def test_assistant_status_does_not_require_provider_network(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["assistant-status"]), 0)
        self.assertIn("provider=deterministic", output.getvalue())


if __name__ == "__main__":
    unittest.main()
