"""Telegram update parsing helpers."""

from __future__ import annotations

from typing import Any

from gaon.integrations.telegram.contracts import TelegramChat, TelegramDiscoveredChat, TelegramMessage, TelegramUpdate, TelegramUser
from gaon.runtime.errors import MappingError

MESSAGE_PREVIEW_LIMIT = 30


def parse_update(payload: dict, *, received_at: str) -> TelegramMessage:
    update = parse_update_result(payload, received_at=received_at)
    if update.message is None:
        raise MappingError(update.ignored_reason or "Telegram update did not contain a supported message")
    return update.message


def parse_update_result(payload: dict[str, Any], *, received_at: str) -> TelegramUpdate:
    try:
        update_id = _update_id(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise MappingError("invalid Telegram update_id") from exc

    if "message" not in payload:
        return TelegramUpdate(update_id, None, "unsupported update type")
    try:
        message = payload["message"]
        chat = message["chat"]
        user = message["from"]
        chat_type = str(chat.get("type", "private"))
        if chat_type != "private":
            return TelegramUpdate(update_id, None, "non-private chat ignored")
        text = message.get("text")
        if not isinstance(text, str) or not text:
            return TelegramUpdate(update_id, None, "non-text message ignored")
        return TelegramUpdate(
            update_id,
            TelegramMessage(
                message_id=str(message["message_id"]),
                chat=TelegramChat(chat_id=str(chat["id"]), chat_type=chat_type, username=chat.get("username"), first_name=chat.get("first_name")),
                user=TelegramUser(user_id=str(user["id"]), username=user.get("username"), first_name=user.get("first_name")),
                text=text,
                received_at=received_at,
            ),
        )
    except KeyError as exc:
        raise MappingError("invalid Telegram update payload") from exc


def discover_private_chats(updates: tuple[dict[str, Any], ...] | list[dict[str, Any]], *, received_at: str) -> tuple[TelegramDiscoveredChat, ...]:
    discovered: dict[str, TelegramDiscoveredChat] = {}
    for payload in updates:
        try:
            update = parse_update_result(payload, received_at=received_at)
        except MappingError:
            continue
        if update.message is None:
            continue
        message = update.message
        discovered.setdefault(
            message.chat.chat_id,
            TelegramDiscoveredChat(
                chat_id=message.chat.chat_id,
                chat_type=message.chat.chat_type,
                username=message.user.username or message.chat.username,
                first_name=message.user.first_name or message.chat.first_name,
                message_preview=_preview(message.text),
            ),
        )
    return tuple(discovered.values())


def _preview(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:MESSAGE_PREVIEW_LIMIT]


def _update_id(payload: dict[str, Any]) -> int:
    value = payload["update_id"]
    if isinstance(value, bool):
        raise ValueError("boolean update_id is invalid")
    return int(value)
