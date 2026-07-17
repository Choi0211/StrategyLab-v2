"""Dry-run Telegram client."""

from __future__ import annotations

from gaon.integrations.telegram.contracts import TelegramResponse


class DryRunTelegramClient:
    def send_message(self, chat_id: str, text: str) -> TelegramResponse:
        return TelegramResponse(chat_id=chat_id, text=text, dry_run=True, correlation_id=f"telegram:{chat_id}")
