"""Confidence contracts for learned items."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

CONFIDENCE_SCHEMA_VERSION = 1


def _versioned_payload(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": CONFIDENCE_SCHEMA_VERSION, "kind": kind, "data": data}


def _load_versioned_json(payload: str, expected_kind: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    if decoded.get("schema_version") != CONFIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported confidence schema version")
    if decoded.get("kind") != expected_kind:
        raise ValueError(f"expected {expected_kind} payload")
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise ValueError("confidence payload data must be an object")
    return data


@dataclass(frozen=True)
class ConfidenceScore:
    """Bounded confidence score for evidence-backed learning."""

    value: float
    reason: str
    evidence_count: int = 0
    validation_state: str = "unvalidated"
    recency: float = 0.0
    conflict_penalty: float = 0.0

    def __post_init__(self) -> None:
        if self.value < 0.0 or self.value > 1.0:
            raise ValueError("confidence value must be between 0.0 and 1.0")
        if not self.reason:
            raise ValueError("confidence reason is required")
        if self.evidence_count < 0:
            raise ValueError("evidence_count must be non-negative")
        if self.recency < 0.0 or self.recency > 1.0:
            raise ValueError("recency must be between 0.0 and 1.0")
        if self.conflict_penalty < 0.0 or self.conflict_penalty > 1.0:
            raise ValueError("conflict_penalty must be between 0.0 and 1.0")

    @property
    def can_approve(self) -> bool:
        """Confidence never approves knowledge, policy, or preferences."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "reason": self.reason,
            "evidence_count": self.evidence_count,
            "validation_state": self.validation_state,
            "recency": self.recency,
            "conflict_penalty": self.conflict_penalty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfidenceScore":
        return cls(
            value=data["value"],
            reason=data["reason"],
            evidence_count=data.get("evidence_count", 0),
            validation_state=data.get("validation_state", "unvalidated"),
            recency=data.get("recency", 0.0),
            conflict_penalty=data.get("conflict_penalty", 0.0),
        )

    def to_json(self) -> str:
        return json.dumps(_versioned_payload("confidence_score", self.to_dict()), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "ConfidenceScore":
        return cls.from_dict(_load_versioned_json(payload, "confidence_score"))
