"""Telegram to conversation runtime bridge."""

from __future__ import annotations

from gaon.integrations.telegram.contracts import TelegramClient, TelegramMessage, TelegramPollResult, TelegramResponse, TelegramUpdate
from gaon.integrations.telegram.formatter import split_message
from gaon.runtime.conversation import ConversationInput, ConversationRuntime
from gaon.runtime.errors import AuthorizationError

MAX_INPUT_TEXT_LENGTH = 4096
TOO_LONG_TEXT = "입력 메시지가 너무 깁니다. 짧게 나누어 다시 보내 주세요."


class TelegramRuntime:
    def __init__(self, conversation: ConversationRuntime, allowed_chat_ids: tuple[str, ...]) -> None:
        self._conversation = conversation
        self._allowed_chat_ids = allowed_chat_ids

    def handle_message(self, message: TelegramMessage, *, dry_run: bool = True) -> tuple[TelegramResponse, ...]:
        if self._allowed_chat_ids and message.chat.chat_id not in self._allowed_chat_ids:
            raise AuthorizationError("telegram chat is not allowed")
        if len(message.text) > MAX_INPUT_TEXT_LENGTH:
            return (TelegramResponse(message.chat.chat_id, TOO_LONG_TEXT, dry_run=dry_run, correlation_id=f"response:{message.message_id}"),)
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
            TelegramResponse(message.chat.chat_id, part, dry_run=dry_run, correlation_id=response.response_id)
            for part in split_message(response.text)
        )


def process_update(update: TelegramUpdate, runtime: TelegramRuntime, client: TelegramClient) -> TelegramPollResult:
    if update.message is None:
        return TelegramPollResult(update.update_id, update.next_offset, "ignored", error=update.ignored_reason)
    try:
        prepared = runtime.handle_message(update.message, dry_run=False)
    except AuthorizationError as exc:
        return TelegramPollResult(update.update_id, update.next_offset, "unauthorized", chat_id=update.message.chat.chat_id, error=str(exc))
    sent: list[TelegramResponse] = []
    for response in prepared:
        sent.append(client.send_message(response.chat_id, response.text))
    return TelegramPollResult(update.update_id, update.next_offset, "sent", chat_id=update.message.chat.chat_id, responses=tuple(sent))
