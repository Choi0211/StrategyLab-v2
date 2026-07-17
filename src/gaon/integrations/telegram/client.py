"""Telegram client implementations."""

from __future__ import annotations

from collections.abc import Callable
import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.runtime.errors import AuthenticationError, ExternalServiceError, RateLimitError, TransportError, mask_secret

MAX_TELEGRAM_RESPONSE_BYTES = 1_000_000


class TelegramBotApiClient:
    """Small Telegram Bot API client with injectable HTTP transport."""

    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
        base_url: str = "https://api.telegram.org",
        max_response_bytes: int = MAX_TELEGRAM_RESPONSE_BYTES,
    ) -> None:
        if not token:
            raise AuthenticationError("telegram bot token is required")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._opener = opener
        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes

    def __repr__(self) -> str:
        return f"TelegramBotApiClient(token={mask_secret(self._token)!r})"

    def get_me(self) -> dict[str, Any]:
        result = self._request("getMe")
        if not isinstance(result, dict):
            raise TransportError("Telegram getMe result must be an object")
        return result

    def get_updates(self, *, offset: int | None = None, timeout: int = 0, limit: int = 100) -> tuple[dict[str, Any], ...]:
        payload: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            payload["offset"] = offset
        result = self._request("getUpdates", payload)
        if not isinstance(result, list):
            raise TransportError("Telegram getUpdates result must be a list")
        return tuple(update for update in result if isinstance(update, dict))

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> TelegramResponse:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        result = self._request("sendMessage", payload)
        if not isinstance(result, dict):
            raise TransportError("Telegram sendMessage result must be an object")
        message_id = str(result.get("message_id", ""))
        return TelegramResponse(chat_id=chat_id, text=text, dry_run=False, correlation_id=f"telegram:{chat_id}:{message_id}", message_id=message_id or None)

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> dict[str, Any] | bool:
        return self._request("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_webhook_info(self) -> dict[str, Any]:
        result = self._request("getWebhookInfo")
        if not isinstance(result, dict):
            raise TransportError("Telegram getWebhookInfo result must be an object")
        return result

    def _request(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        request = Request(
            self._method_url(method),
            data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            raw = response.read(self._max_response_bytes + 1)
        except HTTPError as exc:
            self._raise_http_error(exc)
        except (TimeoutError, socket.timeout, URLError, OSError) as exc:
            raise TransportError("Telegram network request failed") from exc
        if len(raw) > self._max_response_bytes:
            raise TransportError("Telegram response exceeded size limit")
        return self._decode_response(raw)

    def _method_url(self, method: str) -> str:
        return f"{self._base_url}/bot{self._token}/{method}"

    def _decode_response(self, raw: bytes) -> Any:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError("Telegram response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TransportError("Telegram response must be a JSON object")
        if payload.get("ok") is not True:
            self._raise_telegram_error(payload)
        return payload.get("result")

    def _raise_http_error(self, exc: HTTPError) -> None:
        if exc.code in {401, 403}:
            raise AuthenticationError("Telegram authentication failed") from exc
        if exc.code == 429:
            retry_after = self._extract_retry_after(exc)
            suffix = f"; retry_after={retry_after}" if retry_after is not None else ""
            raise RateLimitError(f"Telegram rate limit reached{suffix}") from exc
        if exc.code >= 500:
            raise ExternalServiceError(f"Telegram service returned HTTP {exc.code}") from exc
        raise TransportError(f"Telegram HTTP request failed with status {exc.code}") from exc

    def _raise_telegram_error(self, payload: dict[str, Any]) -> None:
        code = int(payload.get("error_code", 0) or 0)
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        description = str(payload.get("description", "Telegram request failed"))
        if code in {401, 403}:
            raise AuthenticationError(description)
        if code == 429:
            suffix = f"; retry_after={retry_after}" if retry_after is not None else ""
            raise RateLimitError(f"{description}{suffix}")
        if code >= 500:
            raise ExternalServiceError(description)
        raise TransportError(description)

    def _extract_retry_after(self, exc: HTTPError) -> int | None:
        try:
            payload = json.loads(exc.read(MAX_TELEGRAM_RESPONSE_BYTES).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            return None
        value = parameters.get("retry_after")
        return int(value) if isinstance(value, int) else None


class DryRunTelegramClient:
    def send_message(self, chat_id: str, text: str, parse_mode: str | None = None, reply_to_message_id: str | None = None) -> TelegramResponse:
        return TelegramResponse(chat_id=chat_id, text=text, dry_run=True, correlation_id=f"telegram:{chat_id}")
