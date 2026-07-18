import os
import tempfile
import unittest

from gaon.integrations.telegram.contracts import TelegramResponse
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
        client = FakeTelegramClient((_update(20, 2, "가온"),))
        try:
            first = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)
            second = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:01Z", state=store.telegram, runtime_store=store)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(len(client.sent), 1)
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


def _config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
    )


def _update(update_id: int, message_id: int, text: str, *, chat_id: int = 100) -> dict:
    return {"update_id": update_id, "message": {"message_id": message_id, "chat": {"id": chat_id}, "from": {"id": 200}, "text": text}}


if __name__ == "__main__":
    unittest.main()
