"""Telegram to conversation runtime bridge."""

from __future__ import annotations

import time

from gaon.integrations.telegram.contracts import TelegramClient, TelegramMessage, TelegramPollResult, TelegramResponse, TelegramUpdate
from gaon.integrations.telegram.formatter import split_message
from gaon.runtime.conversation import ConversationInput, ConversationRuntime
from gaon.runtime.errors import AuthenticationError, AuthorizationError, ExternalServiceError, RateLimitError, TransportError

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
    try:
        for response in prepared:
            sent.append(_send_with_retry(client, response))
    except (AuthenticationError, AuthorizationError, TransportError) as exc:
        return TelegramPollResult(update.update_id, update.next_offset, "send_failed", chat_id=update.message.chat.chat_id, responses=tuple(sent), error=_classify_send_error(exc))
    return TelegramPollResult(update.update_id, update.next_offset, "sent", chat_id=update.message.chat.chat_id, responses=tuple(sent))


def _send_with_retry(client: TelegramClient, response: TelegramResponse, *, max_attempts: int = 3) -> TelegramResponse:
    attempt = 0
    while True:
        attempt += 1
        try:
            return client.send_message(response.chat_id, response.text)
        except (ExternalServiceError, RateLimitError, TransportError) as exc:
            if isinstance(exc, TransportError) and not _is_retryable_transport(exc):
                raise
            if attempt >= max_attempts:
                raise TransportError(_classify_send_error(exc)) from exc
            time.sleep(_retry_delay(exc, attempt))


def _is_retryable_transport(exc: TransportError) -> bool:
    return "network" in str(exc).casefold() or "timeout" in str(exc).casefold()


def _retry_delay(exc: Exception, attempt: int) -> float:
    message = str(exc)
    if "retry_after=" in message:
        try:
            return min(float(message.rsplit("retry_after=", 1)[1].split(";", 1)[0]), 1.0)
        except ValueError:
            return 0.05
    return min(0.05 * attempt, 0.2)


def _classify_send_error(exc: Exception) -> str:
    if str(exc).startswith("TELEGRAM_"):
        return str(exc)
    if isinstance(exc, AuthenticationError):
        return "TELEGRAM_AUTH_ERROR"
    if isinstance(exc, AuthorizationError):
        return "TELEGRAM_AUTHORIZATION_ERROR"
    if isinstance(exc, RateLimitError):
        return "TELEGRAM_RATE_LIMIT"
    if isinstance(exc, ExternalServiceError):
        return "TELEGRAM_TRANSIENT_ERROR"
    return "TELEGRAM_SEND_ERROR"
