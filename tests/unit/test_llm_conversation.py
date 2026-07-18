import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.intents import Intent
from gaon.runtime.llm_conversation import (
    LLMConversationBrain,
    LLMConversationMessage,
    LLMConversationRequest,
    SQLiteConversationRepository,
)
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


class LLMConversationBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v22(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 22)
        version = self.connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
        self.assertEqual(version, 22)

    def test_deterministic_fallback_persists_session_and_messages(self) -> None:
        brain = LLMConversationBrain(GaonRuntimeConfig(), self.repository, event_store=SQLiteEventStore(self.connection))
        response = brain.respond(_request("안녕하세요"))

        self.assertEqual(response.intent, Intent.GREETING)
        self.assertIn("영하님", response.text)
        self.assertEqual(response.route, "rule_based")
        self.assertEqual(len(self.repository.list_messages("telegram:1")), 2)

    def test_approval_boundary_bypasses_provider(self) -> None:
        brain = LLMConversationBrain(GaonRuntimeConfig(assistant_enabled=True), self.repository)
        response = brain.respond(_request("삼성전자 매수 주문 승인해줘"))

        self.assertTrue(response.approval_required)
        self.assertEqual(response.provider, "deterministic")
        self.assertIn("provider bypassed for approval boundary", response.warnings)

    def test_versioned_message_json_round_trip(self) -> None:
        message = LLMConversationMessage("m1", "s1", "user", "안녕", "greeting", "input", ("ref",), ("warn",), (), "2026-07-19T00:00:00Z")
        restored = LLMConversationMessage.from_json(message.to_json())
        self.assertEqual(restored, message)

    def test_unsupported_message_version_fails_closed(self) -> None:
        message = LLMConversationMessage("m1", "s1", "user", "안녕", "greeting", "input", (), (), (), "2026-07-19T00:00:00Z")
        payload = message.to_json()
        payload["schema_version"] = 999
        with self.assertRaises(ValueError):
            LLMConversationMessage.from_json(payload)

    def test_provider_response_is_used_when_enabled(self) -> None:
        config = GaonRuntimeConfig(assistant_enabled=True)
        brain = LLMConversationBrain(config, self.repository)
        from gaon.runtime import llm_conversation

        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: _FakeProvider()
        try:
            response = brain.respond(_request("도움말"))
        finally:
            llm_conversation.build_assistant_provider = original
        self.assertEqual(response.text, "영하님, provider response입니다.")
        self.assertEqual(response.provider, "fake")


class _FakeProvider:
    @property
    def capabilities(self):
        raise NotImplementedError

    def health(self):
        raise NotImplementedError

    def respond(self, request):
        return AssistantProviderResponse(text="영하님, provider response입니다.", provider_name="fake", route="provider")


def _request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest(
        session_id="telegram:1",
        user_ref="user:youngha",
        source="telegram",
        text=text,
        received_at="2026-07-19T00:00:00Z",
        message_id=f"message:{text}",
    )


if __name__ == "__main__":
    unittest.main()
