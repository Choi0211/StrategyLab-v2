"""Explicit Learning Memory repository migrations."""

from __future__ import annotations

import json
from typing import Any

from gaon.learning.serialization import LEARNING_REPOSITORY_KIND, LEARNING_REPOSITORY_SCHEMA_VERSION


def migrate_repository_json(payload: str) -> str:
    """Migrate a supported legacy repository payload to the current schema."""

    decoded = json.loads(payload)
    kind = decoded.get("kind")
    version = decoded.get("schema_version")
    if kind != LEARNING_REPOSITORY_KIND:
        raise ValueError("expected learning_repository payload")
    if version == LEARNING_REPOSITORY_SCHEMA_VERSION:
        return json.dumps(decoded, sort_keys=True)
    if version == 0:
        migrated = {
            "schema_version": LEARNING_REPOSITORY_SCHEMA_VERSION,
            "kind": LEARNING_REPOSITORY_KIND,
            "records": _require_list(decoded, "records"),
            "claims": _optional_list(decoded, "claims"),
            "audit_events": _require_list(decoded, "audit_events"),
        }
        return json.dumps(migrated, sort_keys=True)
    raise ValueError("unsupported Learning Repository schema version")


def _require_list(decoded: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = decoded.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _optional_list(decoded: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = decoded.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value
