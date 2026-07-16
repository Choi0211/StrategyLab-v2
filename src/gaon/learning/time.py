"""Time validation helpers for Learning Memory."""

from __future__ import annotations

from datetime import UTC, datetime


def validate_iso8601_utc(value: str, field: str) -> None:
    """Require an ISO 8601 timestamp with UTC timezone."""

    if not value:
        raise ValueError(f"{field} is required")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO 8601 UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{field} must be UTC")
