"""Telegram transport helpers."""

from __future__ import annotations

from gaon.integrations.telegram.contracts import TelegramChat, TelegramMessage, TelegramUser
from gaon.runtime.errors import MappingError


def parse_update(payload: dict, *, received_at: str) -> TelegramMessage:
    try:
        message = payload["message"]
        chat = message["chat"]
        user = message["from"]
        return TelegramMessage(
            message_id=str(message["message_id"]),
            chat=TelegramChat(chat_id=str(chat["id"]), chat_type=str(chat.get("type", "private"))),
            user=TelegramUser(user_id=str(user["id"]), username=user.get("username")),
            text=str(message.get("text", "")),
            received_at=received_at,
        )
    except KeyError as exc:
        raise MappingError("invalid Telegram update payload") from exc
