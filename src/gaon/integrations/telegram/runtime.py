"""Telegram to conversation runtime bridge."""

from __future__ import annotations

from gaon.integrations.telegram.contracts import TelegramMessage, TelegramResponse
from gaon.integrations.telegram.formatter import split_message
from gaon.runtime.conversation import ConversationInput, ConversationRuntime
from gaon.runtime.errors import AuthorizationError


class TelegramRuntime:
    def __init__(self, conversation: ConversationRuntime, allowed_chat_ids: tuple[str, ...]) -> None:
        self._conversation = conversation
        self._allowed_chat_ids = allowed_chat_ids

    def handle_message(self, message: TelegramMessage) -> tuple[TelegramResponse, ...]:
        if self._allowed_chat_ids and message.chat.chat_id not in self._allowed_chat_ids:
            raise AuthorizationError("telegram chat is not allowed")
        response = self._conversation.handle(
            ConversationInput(
                source="telegram",
                user_id=message.user.user_id,
                conversation_id=message.chat.chat_id,
                message_id=message.message_id,
                text=message.text,
                received_at=message.received_at,
            )
        )
        return tuple(
            TelegramResponse(message.chat.chat_id, part, dry_run=True, correlation_id=response.response_id)
            for part in split_message(response.text)
        )
