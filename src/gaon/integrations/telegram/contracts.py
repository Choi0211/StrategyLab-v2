"""Telegram contracts without network dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TelegramUser:
    user_id: str
    username: str | None = None


@dataclass(frozen=True)
class TelegramChat:
    chat_id: str
    chat_type: str = "private"


@dataclass(frozen=True)
class TelegramMessage:
    message_id: str
    chat: TelegramChat
    user: TelegramUser
    text: str
    received_at: str


@dataclass(frozen=True)
class TelegramResponse:
    chat_id: str
    text: str
    dry_run: bool
    correlation_id: str


class TelegramClient(Protocol):
    def send_message(self, chat_id: str, text: str) -> TelegramResponse: ...


class TelegramTransport(Protocol):
    def poll_once(self) -> tuple[TelegramMessage, ...]: ...
