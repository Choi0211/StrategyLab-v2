import sqlite3
import unittest

from gaon.runtime.conversation_context import (
    ConversationContextOrchestrator,
    ConversationSummaryRecord,
    ContextSourceType,
    SQLiteConversationSummaryRepository,
)
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


class ConversationContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v23(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 23)
        row = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_summaries'").fetchone()
        self.assertIsNotNone(row)

    def test_recent_conversation_context_is_bounded_and_referenced(self) -> None:
        brain = LLMConversationBrain(GaonRuntimeConfig(), self.repository)
        for index in range(4):
            brain.respond(_request(f"안녕 {index}", f"message:{index}"))

        context = ConversationContextOrchestrator(self.connection, self.repository, recent_message_limit=3, max_chars=300).build("telegram:1")

        self.assertEqual(len(context.items), 3)
        self.assertTrue(all(item.source_type is ContextSourceType.RECENT_CONVERSATION for item in context.items))
        self.assertLessEqual(len(context.to_prompt_context()), 500)
        self.assertTrue(context.references)

    def test_runtime_tables_are_used_without_fabrication(self) -> None:
        self.connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "corr-1", "completed", "completed", '{"status":"completed"}', "2026-07-19T00:00:00Z", "2026-07-19T00:00:00Z"),
        )
        context = ConversationContextOrchestrator(self.connection, self.repository).build("missing-session")

        self.assertEqual(context.items[0].source_type, ContextSourceType.V5_PIPELINE)
        self.assertEqual(context.warnings, ())

    def test_empty_context_warns(self) -> None:
        context = ConversationContextOrchestrator(self.connection, self.repository).build("missing-session")
        self.assertEqual(context.items, ())
        self.assertIn("no verified context available", context.warnings)

    def test_summary_repository_round_trip(self) -> None:
        LLMConversationBrain(GaonRuntimeConfig(), self.repository).respond(_request("안녕", "message:summary"))
        summaries = SQLiteConversationSummaryRepository(self.connection)
        summaries.add(ConversationSummaryRecord("summary-1", "telegram:1", ("ref-1",), "요약", "2026-07-19T00:00:00Z"))

        self.assertEqual(summaries.list_for_session("telegram:1")[0].summary_text, "요약")


def _request(text: str, message_id: str) -> LLMConversationRequest:
    return LLMConversationRequest(
        session_id="telegram:1",
        user_ref="user:youngha",
        source="telegram",
        text=text,
        received_at="2026-07-19T00:00:00Z",
        message_id=message_id,
    )


if __name__ == "__main__":
    unittest.main()
