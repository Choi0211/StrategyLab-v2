import unittest

from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.integrations.telegram.runtime import TelegramRuntime
from gaon.integrations.telegram.transport import parse_update
from gaon.learning import ConfidenceScore, EvidenceRecord, EvidenceType, InMemoryLearningRepository, LearningRecord, LearningRecordType, RevalidationSchedule, RevalidationStatus
from gaon.runtime.cli import discover_chats, poll_once
from gaon.runtime import ConversationRuntime
from gaon.runtime.assistant_provider import AssistantProviderResponse
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.memory_context import MemoryContextBuilder
from gaon.runtime.storage import RuntimeStateStore


class FakeTelegramClient:
    def __init__(self, updates: tuple[dict, ...]) -> None:
        self.updates = updates
        self.sent: list[TelegramResponse] = []
        self.offset = None

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.offset = offset
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        response = TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"fake:{len(self.sent)}", message_id=str(len(self.sent) + 1))
        self.sent.append(response)
        return response


class FakeAssistantProvider:
    @property
    def capabilities(self):
        return None

    def health(self):
        return None

    def respond(self, request):
        return AssistantProviderResponse("영하님, provider telegram 응답입니다.", route="provider", references=request.references, provider_name="fake", model="fake")


class TelegramProductionConnectionFlowTest(unittest.TestCase):
    def config(self) -> GaonRuntimeConfig:
        return GaonRuntimeConfig(
            mode="execute",
            dry_run=False,
            telegram_enabled=True,
            telegram_bot_token="synthetic-token",
            telegram_allowed_chat_ids=("100",),
            approval_signing_secret="synthetic-approval-secret",
        )

    def test_get_updates_to_discover_chat_flow(self) -> None:
        client = FakeTelegramClient(
            (
                {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200, "username": "youngha"}, "text": "/start"}},
                {"update_id": 2, "message": {"message_id": 2, "chat": {"id": 100}, "from": {"id": 200, "username": "youngha"}, "text": "/status"}},
            )
        )

        chats = discover_chats(client, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].chat_id, "100")
        self.assertEqual(chats[0].username, "youngha")

    def test_allowed_status_update_to_send_message_flow(self) -> None:
        client = FakeTelegramClient(({"update_id": 20, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "/status"}},))

        results = poll_once(client, self.config(), offset=20, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(client.offset, 20)
        self.assertEqual(results[0].status, "sent")
        self.assertEqual(results[0].next_offset, 21)
        self.assertEqual(client.sent[0].chat_id, "100")
        self.assertIn("dry-run", client.sent[0].text)

    def test_poll_response_once_then_repeated_poll_has_no_duplicate_response(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(({"update_id": 22, "message": {"message_id": 7, "chat": {"id": 100}, "from": {"id": 200}, "text": "/status"}},))
        try:
            first = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:00Z", state=store.telegram)
            second = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:01Z", state=store.telegram)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(len(client.sent), 1)
            self.assertEqual(client.offset, 23)
        finally:
            store.close()

    def test_korean_natural_text_to_telegram_response_flow(self) -> None:
        client = FakeTelegramClient(({"update_id": 25, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "안녕"}},))

        results = poll_once(client, self.config(), offset=25, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(results[0].status, "sent")
        self.assertEqual(results[0].next_offset, 26)
        self.assertEqual(client.sent[0].chat_id, "100")
        self.assertIn("영하님", client.sent[0].text)

    def test_telegram_memory_query_uses_context_flow(self) -> None:
        repository = InMemoryLearningRepository()
        evidence = (EvidenceRecord("ev-tg-memory", EvidenceType.RESEARCH, "telegram-fixture", "telegram memory evidence"),)
        repository.add(
            LearningRecord(
                "tg-memory",
                LearningRecordType.KNOWLEDGE_CLAIM,
                "ORB Telegram memory context",
                "strategy-research",
                "StrategyLab",
                "ORB",
                "KRX",
                "2026-07-17T00:00:00Z",
                "2026-07-17T00:00:00Z",
                1,
                evidence,
                ConfidenceScore(0.8, "fixture", 1, "need_validation", 1.0, 0.0),
                RevalidationSchedule("rv-tg", "tg-memory", "scheduled", "2026-08-01T00:00:00Z", "monthly", RevalidationStatus.PENDING, "strategy-research", "StrategyLab", "ORB", "KRX"),
                "audit:tg",
            )
        )
        runtime = TelegramRuntime(ConversationRuntime(context_builder=MemoryContextBuilder(repository)), allowed_chat_ids=("100",))
        message = parse_update({"update_id": 50, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "/memory ORB"}}, received_at="2026-07-17T00:00:00Z")

        responses = runtime.handle_message(message)

        self.assertIn("관련 기록 1건", responses[0].text)
        self.assertIn("tg-memory", responses[0].text)

    def test_telegram_provider_flow_fake_transport(self) -> None:
        runtime = TelegramRuntime(ConversationRuntime(assistant_provider=FakeAssistantProvider()), allowed_chat_ids=("100",))
        message = parse_update({"update_id": 60, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "안녕"}}, received_at="2026-07-17T00:00:00Z")

        responses = runtime.handle_message(message)

        self.assertIn("provider telegram", responses[0].text)

    def test_unauthorized_update_does_not_send_message_flow(self) -> None:
        client = FakeTelegramClient(({"update_id": 30, "message": {"message_id": 1, "chat": {"id": 999}, "from": {"id": 200}, "text": "/status"}},))

        results = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(results[0].status, "unauthorized")
        self.assertEqual(client.sent, [])

    def test_long_response_parts_are_sent_to_same_chat_flow(self) -> None:
        client = FakeTelegramClient(({"update_id": 40, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "/help"}},))

        results = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(results[0].status, "sent")
        self.assertTrue(client.sent)
        self.assertTrue(all(response.chat_id == "100" for response in client.sent))


if __name__ == "__main__":
    unittest.main()
