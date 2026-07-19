import os
import tempfile
import unittest

from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall
from gaon.runtime.cli import TELEGRAM_POLL_OFFSET_KEY, poll_once
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore


class FakeTelegramClient:
    def __init__(self, updates: tuple[dict, ...]) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []
        self.calls: list[int | None] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.calls.append(offset)
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


class TelegramConversationAgentTests(unittest.TestCase):
    def test_general_korean_message_uses_persistent_conversation_brain(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(10, 1, "안녕"),))
        try:
            result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertIn("영하님", client.sent[0][1])
            messages = store.conversations.list_messages("telegram:100")
            self.assertEqual(len(messages), 2)
            self.assertEqual(store.telegram_conversations.resolve("100", now="2026-07-19T00:00:01Z").session_id, "telegram:100")
        finally:
            store.close()

    def test_repeated_poll_does_not_duplicate_telegram_reply(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(20, 2, "가온 상태 알려줘"),))
        try:
            config = _config(assistant_enabled=True)
            first = poll_once(client, config, offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)
            second = poll_once(client, config, offset=None, received_at="2026-07-19T00:00:01Z", state=store.telegram, runtime_store=store)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(len(client.sent), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="runtime_status")), 1)
        finally:
            store.close()

    def test_restart_same_db_does_not_replay_old_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            first_store = RuntimeStateStore(db)
            try:
                poll_once(FakeTelegramClient((_update(30, 3, "도움말"),)), _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=first_store.telegram, runtime_store=first_store)
            finally:
                first_store.close()

            second_store = RuntimeStateStore(db)
            client = FakeTelegramClient((_update(30, 3, "도움말"),))
            try:
                result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:01Z", state=second_store.telegram, runtime_store=second_store)

                self.assertEqual(result[0].status, "duplicate")
                self.assertEqual(client.calls[0], 31)
                self.assertEqual(client.sent, [])
                self.assertEqual(second_store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 31)
            finally:
                second_store.close()

    def test_unauthorized_message_does_not_create_conversation(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(40, 4, "안녕", chat_id=999),))
        try:
            result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "unauthorized")
            self.assertEqual(store.conversations.list_messages("telegram:999"), ())
            self.assertEqual(client.sent, [])
        finally:
            store.close()

    def test_openai_compatible_tool_roundtrip_sends_telegram_response(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(50, 5, "현재 챔피언 상태와 가온 상태를 같이 알려줘"),))
        provider = _FakeOllamaToolProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertEqual(client.sent[0][1], "챔피언과 런타임 상태를 확인했습니다, 영하님.")
            self.assertEqual(provider.calls, 2)
            self.assertEqual({record.tool_name for record in store.tool_audit.list()}, {"champion_status", "runtime_status"})
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()

    def test_openai_compatible_normal_response_sends_telegram_response(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(60, 6, "안녕하세요 가온"),))
        provider = _FakeOllamaContentProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertEqual(client.sent[0][1], "안녕하세요, 영하님. 가온입니다.")
            self.assertEqual(provider.calls, 1)
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()

    def test_telegram_multi_turn_tool_result_synthesis_reuses_prior_results(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        store._connection.execute(
            "INSERT OR REPLACE INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            ("default", "champion-version:1", '{"strategy_ref":"turtle_v5","fingerprint":"abc123","revision":1}', "2026-07-19T00:00:00Z"),
        )
        store._connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-telegram", "corr", "completed", "promotion_approval", "{}", "2026-07-19T00:00:00Z", "2026-07-19T00:00:00Z"),
        )
        client = FakeTelegramClient(
            (
                _update(70, 7, "현재 챔피언 상태 알려줘"),
                _update(71, 8, "최근 v5 파이프라인 이력 알려줘"),
                _update(72, 9, "방금 내용 종합해서 쉽게 설명해줘"),
            )
        )
        provider = _FakeSynthesisProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual([item.status for item in result], ["sent", "sent", "sent"])
            self.assertIn("종합", client.sent[-1][1])
            self.assertEqual(len(store.tool_audit.list(tool_name="champion_status")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="v5_pipeline_history")), 1)
            self.assertIn("[champion_status]", provider.prompts[-1])
            self.assertIn("[v5_pipeline_history]", provider.prompts[-1])
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()


class _FakeOllamaToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(
                    AssistantToolCall("call-champion", "champion_status", {"slot": "default"}),
                    AssistantToolCall("call-runtime", "runtime_status", {}),
                ),
            )
        return AssistantProviderResponse(text="챔피언과 런타임 상태를 확인했습니다, 영하님.", provider_name="openai-compatible")


class _FakeOllamaContentProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        return AssistantProviderResponse(text="안녕하세요, 영하님. 가온입니다.", provider_name="openai-compatible")

class _FakeSynthesisProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def respond(self, request):
        self.prompts.append(request.prompt or request.text)
        return AssistantProviderResponse(text="챔피언과 v5 파이프라인 상태를 종합했습니다, 영하님.", provider_name="openai-compatible")


def _config(*, assistant_enabled: bool = False, assistant_provider: str = "deterministic") -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
        assistant_enabled=assistant_enabled,
        assistant_provider=assistant_provider,
        assistant_api_key="ollama-dummy-key",
        assistant_base_url="http://ollama.invalid/v1",
        assistant_model="qwen3:8b",
    )


def _update(update_id: int, message_id: int, text: str, *, chat_id: int = 100) -> dict:
    return {"update_id": update_id, "message": {"message_id": message_id, "chat": {"id": chat_id}, "from": {"id": 200}, "text": text}}


if __name__ == "__main__":
    unittest.main()
