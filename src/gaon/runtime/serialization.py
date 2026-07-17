"""Runtime JSON serialization helpers."""

from __future__ import annotations

import json
from typing import Any


def dumps_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def loads_json(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed runtime JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("runtime JSON payload must be an object")
    return payload
