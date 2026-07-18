import os
import tempfile
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_worker import TelegramPollingWorker


class RuntimeServiceFlowTest(unittest.TestCase):
    def test_restart_recovery_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            store.save_offset("100", 99, "2026-07-17T00:00:00Z")
            self.assertTrue(GaonRuntimeService(GaonRuntimeConfig(), store).start().running)
            store.close()

            restored = RuntimeStateStore(db)
            self.assertEqual(restored.get_offset("100"), 99)
            self.assertTrue(GaonRuntimeService(GaonRuntimeConfig(), restored).start().running)
            restored.close()

    def test_telegram_runtime_tick_response_restart_and_failure_recovery_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            update = {"update_id": 50, "message": {"message_id": 5, "chat": {"id": 100}, "from": {"id": 200}, "text": "/status"}}
            store = RuntimeStateStore(db)
            client = _RecoveringTelegramClient((update,))
            try:
                worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: client)
                self.assertEqual(worker.tick().error_type, "RuntimeError")
                self.assertEqual(worker.tick().results[0].status, "sent")
                self.assertEqual(worker.tick().results[0].status, "duplicate")
                self.assertEqual(len(client.sent), 1)
            finally:
                store.close()

            reopened = RuntimeStateStore(db)
            replay_client = _TelegramFlowClient((update,))
            try:
                replay_worker = TelegramPollingWorker(_execute_telegram_config(), reopened, client_factory=lambda _: replay_client)
                duplicate = replay_worker.tick()

                self.assertEqual(duplicate.results[0].status, "duplicate")
                self.assertEqual(replay_client.offset, 51)
                self.assertEqual(replay_client.sent, [])
            finally:
                reopened.close()

    def test_telegram_runtime_tick_keeps_unauthorized_message_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = _TelegramFlowClient(({"update_id": 60, "message": {"message_id": 6, "chat": {"id": 999}, "from": {"id": 200}, "text": "/status"}},))
        try:
            result = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: client).tick()

            self.assertEqual(result.results[0].status, "unauthorized")
            self.assertEqual(client.sent, [])
            self.assertEqual(store.telegram.get_offset("__telegram_poll__"), 61)
        finally:
            store.close()


class _TelegramFlowClient:
    def __init__(self, updates: tuple[dict, ...]) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []
        self.offset = None

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.offset = offset
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


class _RecoveringTelegramClient(_TelegramFlowClient):
    def __init__(self, updates: tuple[dict, ...]) -> None:
        super().__init__(updates)
        self.fail_next = True

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("temporary telegram failure")
        return super().get_updates(offset=offset, timeout=timeout, limit=limit)


def _execute_telegram_config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
    )


if __name__ == "__main__":
    unittest.main()
