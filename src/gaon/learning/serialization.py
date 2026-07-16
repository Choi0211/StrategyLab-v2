"""Versioned JSON serialization for Learning Memory repositories."""

from __future__ import annotations

import json
from typing import Any

from gaon.learning.contracts import AuditEvent, LearningRecord

LEARNING_REPOSITORY_SCHEMA_VERSION = 1
LEARNING_REPOSITORY_KIND = "learning_repository"


def repository_to_json(records: tuple[LearningRecord, ...], audit_events: tuple[AuditEvent, ...]) -> str:
    """Serialize repository state as deterministic versioned JSON."""

    payload = {
        "schema_version": LEARNING_REPOSITORY_SCHEMA_VERSION,
        "kind": LEARNING_REPOSITORY_KIND,
        "records": [record.to_dict() for record in records],
        "audit_events": [event.to_dict() for event in audit_events],
    }
    return json.dumps(payload, sort_keys=True)


def repository_from_json(payload: str) -> tuple[tuple[LearningRecord, ...], tuple[AuditEvent, ...]]:
    """Load repository state from supported versioned JSON."""

    decoded = json.loads(payload)
    if decoded.get("kind") != LEARNING_REPOSITORY_KIND:
        raise ValueError("expected learning_repository payload")
    if decoded.get("schema_version") != LEARNING_REPOSITORY_SCHEMA_VERSION:
        raise ValueError("unsupported Learning Repository schema version")
    records = tuple(LearningRecord.from_dict(record) for record in _require_list(decoded, "records"))
    audit_events = tuple(AuditEvent.from_dict(event) for event in _require_list(decoded, "audit_events"))
    return records, audit_events


def _require_list(decoded: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = decoded.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field} items must be objects")
    return value
