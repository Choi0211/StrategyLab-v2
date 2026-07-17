"""Runtime error hierarchy with safe user-facing messages."""

from __future__ import annotations


class GaonRuntimeError(Exception):
    """Base runtime error."""


class ConfigurationError(GaonRuntimeError):
    """Invalid runtime configuration."""


class AuthenticationError(GaonRuntimeError):
    """Authentication failed."""


class AuthorizationError(GaonRuntimeError):
    """Authorization failed."""


class TransportError(GaonRuntimeError):
    """Transport failed."""


class ExternalServiceError(GaonRuntimeError):
    """External service failed."""


class RateLimitError(GaonRuntimeError):
    """Rate limit reached."""


class MappingError(GaonRuntimeError):
    """Payload mapping failed."""


class SyncError(GaonRuntimeError):
    """Sync failed."""


class CommandError(GaonRuntimeError):
    """Command failed."""


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def redact_mapping(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        normalized = key.lower()
        if any(token in normalized for token in ("token", "secret", "api_key", "password")):
            redacted[key] = mask_secret(str(value) if value is not None else None)
        else:
            redacted[key] = value
    return redacted
