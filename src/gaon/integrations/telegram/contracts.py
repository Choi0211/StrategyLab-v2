"""Telegram contracts without network dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TelegramUser:
    user_id: str
    username: str | None = None
    first_name: str | None = None


@dataclass(frozen=True)
class TelegramChat:
    chat_id: str
    chat_type: str = "private"
    username: str | None = None
    first_name: str | None = None


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
    message_id: str | None = None


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    message: TelegramMessage | None
    ignored_reason: str | None = None

    @property
    def next_offset(self) -> int:
        return self.update_id + 1


@dataclass(frozen=True)
class TelegramDiscoveredChat:
    chat_id: str
    chat_type: str
    username: str | None
    first_name: str | None
    message_preview: str


@dataclass(frozen=True)
class TelegramPollResult:
    update_id: int
    next_offset: int
    status: str
    chat_id: str | None = None
    responses: tuple[TelegramResponse, ...] = ()
    error: str | None = None


class TelegramClient(Protocol):
    def send_message(self, chat_id: str, text: str, parse_mode: str | None = None, reply_to_message_id: str | None = None) -> TelegramResponse: ...


class TelegramTransport(Protocol):
    def poll_once(self) -> tuple[TelegramMessage, ...]: ...
