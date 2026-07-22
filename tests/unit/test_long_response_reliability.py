from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from gaon.integrations.telegram.contracts import TelegramChat, TelegramMessage, TelegramResponse, TelegramUpdate, TelegramUser
from gaon.integrations.telegram.formatter import split_message
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.runtime.assistant_provider import AssistantProviderResponse, ProviderCapabilities, ProviderHealth, ProviderTimeoutError, ProviderUnavailableError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation import ConversationResponse
from gaon.runtime.errors import ExternalServiceError, TransportError
from gaon.runtime.intents import Intent
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.providers import OpenAICompatibleAssistantProvider
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-22T00:00:00Z"


class LongResponseReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_telegram_chunking_preserves_payload_order_under_limit(self) -> None:
        text = "\n\n".join(f"문단 {index}: " + ("가온 긴 응답 검증 " * 70) for index in range(18))
        chunks = split_message(text)

        self.assertGreater(len(text), 10000)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))
        self.assertEqual(_without_prefixes(chunks), text)
        self.assertTrue(chunks[0].startswith("[1/"))

    def test_telegram_chunking_handles_markdown_and_code_blocks_as_plain_text(self) -> None:
        text = ("**bold** [link](https://example.invalid)\n```python\nprint('gaon')\n```\n" * 180)
        chunks = split_message(text)

        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))
        self.assertEqual(_without_prefixes(chunks), text)

    def test_provider_finish_reason_length_marks_truncation_without_reasoning_leak(self) -> None:
        opener = _SequenceOpener([
            {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "부분 응답", "reasoning": "hidden reasoning"}}]}
        ])
        provider = OpenAICompatibleAssistantProvider(
            api_key="ollama-dummy-key",
            base_url="http://ollama.invalid/v1",
            model="qwen3:8b",
            enabled=True,
            opener=opener,
        )

        response = provider.respond(_assistant_request("긴 응답"))

        self.assertTrue(response.truncated)
        self.assertEqual(response.finish_reason, "length")
        self.assertIn("LLM_TRUNCATED", response.warnings)
        self.assertNotIn("hidden reasoning", response.text)

    def test_single_continuation_completes_truncated_response(self) -> None:
        provider = _ScriptedProvider(
            (
                AssistantProviderResponse("첫 부분입니다.", provider_name="fake", finish_reason="length", truncated=True, warnings=("LLM_TRUNCATED",)),
                AssistantProviderResponse("마무리 문단입니다.", provider_name="fake", finish_reason="stop"),
            )
        )

        response = self._brain(provider).respond(_request("긴 한국어 보고서를 작성해줘"))

        self.assertEqual(provider.calls, 2)
        self.assertIn("첫 부분입니다.", response.text)
        self.assertIn("마무리 문단입니다.", response.text)
        self.assertNotIn("max continuations reached", response.warnings)

    def test_multi_continuation_stops_at_configured_limit_with_partial_text(self) -> None:
        provider = _ScriptedProvider(
            (
                AssistantProviderResponse("A", provider_name="fake", finish_reason="length", truncated=True, warnings=("LLM_TRUNCATED",)),
                AssistantProviderResponse("B", provider_name="fake", finish_reason="length", truncated=True, warnings=("LLM_TRUNCATED",)),
                AssistantProviderResponse("C", provider_name="fake", finish_reason="length", truncated=True, warnings=("LLM_TRUNCATED",)),
            )
        )

        response = self._brain(provider, max_continuations=1).respond(_request("계속 이어서 작성해줘"))

        self.assertEqual(provider.calls, 2)
        self.assertEqual(response.text, "A\n\nB")
        self.assertIn("max continuations reached", response.warnings)

    def test_continuation_failure_keeps_initial_partial_response(self) -> None:
        provider = _ScriptedProvider(
            (
                AssistantProviderResponse("첫 부분은 유효합니다.", provider_name="fake", finish_reason="length", truncated=True, warnings=("LLM_TRUNCATED",)),
                ProviderUnavailableError("down"),
            )
        )

        response = self._brain(provider).respond(_request("긴 응답"))

        self.assertIn("첫 부분은 유효합니다.", response.text)
        self.assertIn("continuation failed: ProviderUnavailableError", response.warnings)

    def test_initial_provider_timeout_uses_safe_fallback(self) -> None:
        provider = _TimeoutProvider()

        response = self._brain(provider).respond(_request("안녕하세요 가온"))

        self.assertEqual(response.route, "fallback")
        self.assertTrue(response.text.strip())
        self.assertIn("ProviderTimeoutError", " ".join(response.warnings))

    def test_telegram_transient_send_failure_retries_and_succeeds(self) -> None:
        client = _FlakyTelegramClient((ExternalServiceError("temporary"),))
        runtime = TelegramRuntime(_FixedConversation("안녕하세요" * 2000), allowed_chat_ids=("100",))

        result = process_update(_update("안녕"), runtime, client)

        self.assertEqual(result.status, "sent")
        self.assertGreaterEqual(client.calls, 2)
        self.assertTrue(all(len(text) <= 3900 for text in client.sent_texts))

    def test_telegram_permanent_send_failure_is_classified(self) -> None:
        client = _FlakyTelegramClient((TransportError("bad request"), TransportError("bad request")))
        runtime = TelegramRuntime(_FixedConversation("전송 실패 검증"), allowed_chat_ids=("100",))

        result = process_update(_update("안녕"), runtime, client)

        self.assertEqual(result.status, "send_failed")
        self.assertEqual(result.error, "TELEGRAM_SEND_ERROR")

    def test_long_response_release_check_is_repeatable_on_persistent_db(self) -> None:
        from gaon.runtime.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "gaon-runtime.sqlite")
            self.assertEqual(main(["long-response-release-check", "--db", db]), 0)
            self.assertEqual(main(["long-response-release-check", "--db", db]), 0)
            self.assertEqual(main(["long-response-release-check", "--db", db]), 0)
            store = RuntimeStateStore(db)
            try:
                status = store.status()
                self.assertEqual(status.schema_version, SCHEMA_VERSION)
                rows = store._connection.execute(
                    "SELECT session_id, message_id FROM conversation_messages WHERE session_id LIKE 'long-response-release-check:%' ORDER BY session_id, message_id"
                ).fetchall()
                self.assertEqual(len(rows), 6)
                self.assertEqual(len({str(row[0]) for row in rows}), 3)
                self.assertEqual(len({str(row[1]) for row in rows}), 6)
            finally:
                store.close()

    def _brain(self, provider, *, max_continuations: int = 2) -> LLMConversationBrain:
        return LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible", assistant_max_output_tokens=512, assistant_max_continuations=max_continuations),
            self.repository,
            assistant_provider=provider,
        )


class _ScriptedProvider:
    def __init__(self, responses: tuple[AssistantProviderResponse | Exception, ...]) -> None:
        self.responses = list(responses)
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", "fixture", False, False, 512)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake", True)

    def respond(self, _request):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _TimeoutProvider(_ScriptedProvider):
    def __init__(self) -> None:
        super().__init__(())

    def respond(self, _request):
        self.calls += 1
        raise ProviderTimeoutError("slow")


class _FlakyTelegramClient:
    def __init__(self, failures: tuple[Exception, ...]) -> None:
        self.failures = list(failures)
        self.calls = 0
        self.sent_texts: list[str] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        self.sent_texts.append(text)
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{self.calls}", message_id=str(self.calls))


class _FixedConversation:
    def __init__(self, text: str) -> None:
        self.text = text

    def handle(self, _message):
        return ConversationResponse("response:1", "100", self.text, Intent.UNKNOWN, (), (), (), False, NOW, route="test")


class _SequenceOpener:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads

    def __call__(self, _request, timeout):
        return _FakeHTTPResponse(self.payloads.pop(0))


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        import json

        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, _size: int = -1) -> bytes:
        return self.payload


def _assistant_request(text: str):
    from gaon.runtime.assistant_provider import AssistantRequest

    return AssistantRequest(text, Intent.UNKNOWN, "user:youngha", "conversation:1", NOW, prompt=text)


def _request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest("session:long", "user:youngha", "test", text, NOW, f"message:{text}")


def _update(text: str) -> TelegramUpdate:
    return TelegramUpdate(1, TelegramMessage("1", TelegramChat("100"), TelegramUser("200"), text, NOW))


def _without_prefixes(chunks: tuple[str, ...]) -> str:
    parts = []
    for chunk in chunks:
        if chunk.startswith("[") and "]\n" in chunk.split("\n", 1)[0] + "\n":
            parts.append(chunk.split("\n", 1)[1])
        else:
            parts.append(chunk)
    return "".join(parts)


if __name__ == "__main__":
    unittest.main()
