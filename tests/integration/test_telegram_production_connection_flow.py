import unittest

from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.runtime.cli import discover_chats, poll_once
from gaon.runtime.config import GaonRuntimeConfig


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


class TelegramProductionConnectionFlowTest(unittest.TestCase):
    def config(self) -> GaonRuntimeConfig:
        return GaonRuntimeConfig(mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="synthetic-token", telegram_allowed_chat_ids=("100",))

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
