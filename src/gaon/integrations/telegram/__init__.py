"""Telegram collaboration adapter contracts."""

from gaon.integrations.telegram.client import DryRunTelegramClient, TelegramBotApiClient
from gaon.integrations.telegram.contracts import TelegramChat, TelegramDiscoveredChat, TelegramMessage, TelegramPollResult, TelegramResponse, TelegramUpdate, TelegramUser
from gaon.integrations.telegram.runtime import TelegramRuntime

__all__ = [
    "DryRunTelegramClient",
    "TelegramBotApiClient",
    "TelegramChat",
    "TelegramDiscoveredChat",
    "TelegramMessage",
    "TelegramPollResult",
    "TelegramResponse",
    "TelegramRuntime",
    "TelegramUpdate",
    "TelegramUser",
]
