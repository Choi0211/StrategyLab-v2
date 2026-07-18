import json
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from types import SimpleNamespace
from urllib.error import HTTPError

from gaon.integrations.telegram.client import TelegramBotApiClient
from gaon.integrations.telegram.contracts import TelegramChat, TelegramMessage, TelegramUser
from gaon.integrations.telegram.runtime import MAX_INPUT_TEXT_LENGTH
from gaon.integrations.telegram.runtime import TelegramRuntime
from gaon.integrations.telegram.transport import discover_private_chats, parse_update_result
from gaon.runtime.cli import TELEGRAM_POLL_OFFSET_KEY, TELEGRAM_SMOKE_TEXT, discover_chats, poll_once, send_smoke
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import AuthenticationError, AuthorizationError, ConfigurationError, ExternalServiceError, RateLimitError, TransportError
from gaon.runtime.storage import RuntimeStateStore


class FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


class FakeTelegramHttp:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request, timeout: float):
        body = json.loads(request.data.decode("utf-8")) if request.data else {}
        self.requests.append((request.full_url, body))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return FakeHttpResponse(payload)


class FakeTelegramClient:
    def __init__(self, updates: tuple[dict, ...] = ()) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.last_offset = offset
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


class TelegramProductionConnectionTest(unittest.TestCase):
    def config(self, allowed: tuple[str, ...] = ("100",)) -> GaonRuntimeConfig:
        return GaonRuntimeConfig(
            mode="execute",
            dry_run=False,
            telegram_enabled=True,
            telegram_bot_token="synthetic-token",
            telegram_allowed_chat_ids=allowed,
            approval_signing_secret="synthetic-approval-secret",
        )

    def test_get_me_get_updates_and_send_message_success(self) -> None:
        fake = FakeTelegramHttp(
            [
                {"ok": True, "result": {"id": 1, "username": "YounghaGaonBot", "first_name": "Gaon"}},
                {"ok": True, "result": [{"update_id": 10}]},
                {"ok": True, "result": {"message_id": 77}},
            ]
        )
        client = TelegramBotApiClient("synthetic-token", opener=fake)

        self.assertEqual(client.get_me()["username"], "YounghaGaonBot")
        self.assertEqual(client.get_updates(offset=10)[0]["update_id"], 10)
        response = client.send_message("100", "hello")

        self.assertEqual(response.message_id, "77")
        self.assertEqual(fake.requests[1][1]["offset"], 10)
        self.assertEqual(fake.requests[2][1]["text"], "hello")
        self.assertNotIn("synthetic-token", repr(client))

    def test_http_and_payload_errors_are_mapped_safely(self) -> None:
        cases = (
            (HTTPError("https://example.invalid", 401, "unauthorized", {}, BytesIO(b"{}")), AuthenticationError),
            (HTTPError("https://example.invalid", 429, "limited", {}, BytesIO(b'{"parameters":{"retry_after":3}}')), RateLimitError),
            (HTTPError("https://example.invalid", 500, "server", {}, BytesIO(b"{}")), ExternalServiceError),
            (b"{not json", TransportError),
            ({"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 3}}, RateLimitError),
            (TimeoutError("timeout"), TransportError),
        )
        for payload, error_type in cases:
            with self.subTest(error_type=error_type):
                client = TelegramBotApiClient("synthetic-token", opener=FakeTelegramHttp([payload]))
                with self.assertRaises(error_type) as ctx:
                    client.get_me()
                self.assertNotIn("synthetic-token", str(ctx.exception))

    def test_discover_chats_deduplicates_and_limits_preview(self) -> None:
        updates = (
            {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 100, "type": "private"}, "from": {"id": 1, "username": "yh"}, "text": "가나다라마바사아자차카타파하 long long"}},
            {"update_id": 2, "message": {"message_id": 2, "chat": {"id": 100, "type": "private"}, "from": {"id": 1, "username": "yh"}, "text": "duplicate"}},
            {"update_id": 3, "message": {"message_id": 3, "chat": {"id": -1, "type": "group"}, "from": {"id": 2}, "text": "ignored"}},
        )

        chats = discover_private_chats(updates, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].chat_id, "100")
        self.assertLessEqual(len(chats[0].message_preview), 30)

    def test_update_parsing_ignores_unsupported_shapes(self) -> None:
        self.assertEqual(parse_update_result({"update_id": 1, "callback_query": {}}, received_at="2026-07-17T00:00:00Z").ignored_reason, "unsupported update type")
        self.assertEqual(parse_update_result({"update_id": 2, "message": {"message_id": 1, "chat": {"id": -1, "type": "group"}, "from": {"id": 1}, "text": "/status"}}, received_at="2026-07-17T00:00:00Z").ignored_reason, "non-private chat ignored")
        self.assertEqual(parse_update_result({"update_id": 3, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "photo": []}}, received_at="2026-07-17T00:00:00Z").ignored_reason, "non-text message ignored")
        with self.assertRaises(Exception):
            parse_update_result({"message": {}}, received_at="2026-07-17T00:00:00Z")

    def test_send_smoke_requires_allowed_chat_and_fixed_text(self) -> None:
        client = FakeTelegramClient()

        response = send_smoke(client, self.config(), "100")

        self.assertEqual(response.text, TELEGRAM_SMOKE_TEXT)
        self.assertEqual(client.sent, [("100", TELEGRAM_SMOKE_TEXT)])
        with self.assertRaises(ConfigurationError):
            send_smoke(client, self.config(), "999")

    def test_poll_once_allowed_unauthorized_ignored_and_long_response_split(self) -> None:
        long_text = "/status" + (" " * (MAX_INPUT_TEXT_LENGTH + 1))
        updates = (
            {"update_id": 10, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},
            {"update_id": 11, "message": {"message_id": 2, "chat": {"id": 999}, "from": {"id": 2}, "text": "/status"}},
            {"update_id": 12, "edited_message": {}},
            {"update_id": 13, "message": {"message_id": 3, "chat": {"id": 100}, "from": {"id": 1}, "text": long_text}},
        )
        client = FakeTelegramClient(updates)

        results = poll_once(client, self.config(), offset=10, received_at="2026-07-17T00:00:00Z")

        self.assertEqual(client.last_offset, 10)
        self.assertEqual([result.next_offset for result in results], [11, 12, 13, 14])
        self.assertEqual(results[0].status, "sent")
        self.assertEqual(results[1].status, "unauthorized")
        self.assertEqual(results[2].status, "ignored")
        self.assertEqual(results[3].status, "sent")
        self.assertTrue(client.sent)
        self.assertEqual(client.sent[0][0], "100")
        self.assertNotEqual(client.sent[1][1], long_text)

    def test_poll_once_persists_offset_and_skips_duplicate_on_second_poll(self) -> None:
        store = RuntimeStateStore(":memory:")
        updates = ({"update_id": 10, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},)
        client = FakeTelegramClient(updates)
        try:
            first = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:00Z", state=store.telegram)
            second = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:01Z", state=store.telegram)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(client.last_offset, 11)
            self.assertEqual(store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 11)
            self.assertEqual(len(client.sent), 1)
        finally:
            store.close()

    def test_processed_message_is_skipped_before_response(self) -> None:
        store = RuntimeStateStore(":memory:")
        updates = ({"update_id": 20, "message": {"message_id": 2, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},)
        client = FakeTelegramClient(updates)
        try:
            self.assertTrue(store.telegram.mark_processed("telegram:100:2", "2026-07-17T00:00:00Z"))
            results = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:01Z", state=store.telegram)

            self.assertEqual(results[0].status, "duplicate")
            self.assertEqual(client.sent, [])
            self.assertEqual(store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 21)
        finally:
            store.close()

    def test_restart_reopen_preserves_saved_offset(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                poll_once(FakeTelegramClient(({"update_id": 30, "message": {"message_id": 3, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},)), self.config(), offset=None, received_at="2026-07-17T00:00:00Z", state=store.telegram)
            finally:
                store.close()
            reopened = RuntimeStateStore(db)
            client = FakeTelegramClient(())
            try:
                poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:01Z", state=reopened.telegram)
                self.assertEqual(client.last_offset, 31)
            finally:
                reopened.close()

    def test_explicit_offset_takes_precedence_over_saved_offset(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            store.telegram.save_offset(TELEGRAM_POLL_OFFSET_KEY, 99, "2026-07-17T00:00:00Z")
            poll_once(client, self.config(), offset=10, received_at="2026-07-17T00:00:01Z", state=store.telegram)

            self.assertEqual(client.last_offset, 10)
            self.assertEqual(store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 99)
        finally:
            store.close()

    def test_unauthorized_and_ignored_updates_advance_offset(self) -> None:
        store = RuntimeStateStore(":memory:")
        updates = (
            {"update_id": 40, "message": {"message_id": 4, "chat": {"id": 999}, "from": {"id": 1}, "text": "/status"}},
            {"update_id": 41, "edited_message": {}},
        )
        client = FakeTelegramClient(updates)
        try:
            results = poll_once(client, self.config(), offset=None, received_at="2026-07-17T00:00:00Z", state=store.telegram)

            self.assertEqual([result.status for result in results], ["unauthorized", "ignored"])
            self.assertEqual(store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 42)
            self.assertEqual(client.sent, [])
        finally:
            store.close()

    def test_long_conversation_response_is_split_for_same_chat(self) -> None:
        class LongConversation:
            def handle(self, message):
                return SimpleNamespace(response_id="response:long", text="x" * 4097)

        runtime = TelegramRuntime(LongConversation(), allowed_chat_ids=("100",))
        message = TelegramMessage("1", TelegramChat("100"), TelegramUser("200"), "/help", "2026-07-17T00:00:00Z")

        responses = runtime.handle_message(message, dry_run=False)

        self.assertEqual(len(responses), 2)
        self.assertTrue(all(response.chat_id == "100" for response in responses))
        self.assertTrue(all(response.dry_run is False for response in responses))

    def test_discover_chats_helper_uses_fake_client_without_network(self) -> None:
        client = FakeTelegramClient(({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1, "first_name": "Youngha"}, "text": "/start"}},))
        self.assertEqual(discover_chats(client, received_at="2026-07-17T00:00:00Z")[0].first_name, "Youngha")

    def test_cli_dry_run_commands_do_not_require_tokens(self) -> None:
        for command in ("telegram-get-me", "telegram-discover-chat", "telegram-poll-once"):
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output):
                    from gaon.runtime.cli import main as cli_main

                    self.assertEqual(cli_main([command]), 0)
                self.assertIn("dry-run", output.getvalue())


if __name__ == "__main__":
    unittest.main()
