"""Priority 2 / D1 + D4 - immutable strategy version registry.

Applying (or rolling back to) a strategy never OVERWRITES the previous
one. Every version is an immutable ``StrategyVersion`` record kept in
insertion order; nothing is ever deleted, so the full lineage -
candidate id, spec fingerprint, spec rules, validation summary, and each
activation / deactivation timestamp - is auditable.

Status lifecycle:
    APPLY_READY --(mark_active)--> ACTIVE
    the prior ACTIVE --> PREVIOUS  (deactivated_at set)
    a PREVIOUS version --(mark_active)--> ACTIVE again  (rollback)
    any version --(mark_retired)--> RETIRED  (never offered for activation)

Isolated module - no production wiring, no change to existing
mission/candidate identity (it only *references* a candidate_id).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping
from uuid import uuid4


class StrategyVersionStatus(str, Enum):
    APPLY_READY = "apply_ready"
    ACTIVE = "active"
    PREVIOUS = "previous"
    RETIRED = "retired"


@dataclass(frozen=True)
class StrategyVersion:
    strategy_version_id: str
    family_id: str
    candidate_id: str
    spec_fingerprint: str
    spec_rules: Mapping[str, object]
    validation_summary: Mapping[str, object]
    status: StrategyVersionStatus
    created_at: str
    approved_at: str | None = None
    activated_at: str | None = None
    deactivated_at: str | None = None
    retired_at: str | None = None
    retired_reason: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "strategy_version_id": self.strategy_version_id,
            "family_id": self.family_id,
            "candidate_id": self.candidate_id,
            "spec_fingerprint": self.spec_fingerprint,
            "spec_rules": dict(self.spec_rules),
            "validation_summary": dict(self.validation_summary),
            "status": self.status.value,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "activated_at": self.activated_at,
            "deactivated_at": self.deactivated_at,
            "retired_at": self.retired_at,
            "retired_reason": self.retired_reason,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> "StrategyVersion":
        return cls(
            strategy_version_id=str(raw["strategy_version_id"]),
            family_id=str(raw["family_id"]),
            candidate_id=str(raw["candidate_id"]),
            spec_fingerprint=str(raw["spec_fingerprint"]),
            spec_rules=dict(raw.get("spec_rules") or {}),
            validation_summary=dict(raw.get("validation_summary") or {}),
            status=StrategyVersionStatus(str(raw["status"])),
            created_at=str(raw["created_at"]),
            approved_at=_opt(raw.get("approved_at")),
            activated_at=_opt(raw.get("activated_at")),
            deactivated_at=_opt(raw.get("deactivated_at")),
            retired_at=_opt(raw.get("retired_at")),
            retired_reason=_opt(raw.get("retired_reason")),
        )


def _opt(value: object) -> str | None:
    return str(value) if value is not None else None


class StrategyVersionRegistry:
    """Append-only. No ``delete`` / ``purge`` / ``overwrite`` - the only
    mutations are status transitions, and each keeps the record's own
    history fields."""

    def __init__(self, versions: "list[StrategyVersion] | None" = None) -> None:
        self._versions: list[StrategyVersion] = list(versions or [])

    # --- registration ------------------------------------------------------
    def register_apply_ready(
        self,
        *,
        family_id: str,
        candidate_id: str,
        spec_fingerprint: str,
        spec_rules: Mapping[str, object],
        validation_summary: Mapping[str, object],
        at: str,
    ) -> StrategyVersion:
        version = StrategyVersion(
            strategy_version_id=f"strategy-version:{uuid4().hex[:12]}",
            family_id=family_id,
            candidate_id=candidate_id,
            spec_fingerprint=spec_fingerprint,
            spec_rules=dict(spec_rules),
            validation_summary=dict(validation_summary),
            status=StrategyVersionStatus.APPLY_READY,
            created_at=at,
            approved_at=at,
        )
        self._versions.append(version)
        return version

    # --- reads -----------------------------------------------------------
    def history(self) -> "list[StrategyVersion]":
        return list(self._versions)

    def get(self, strategy_version_id: str) -> StrategyVersion:
        for v in self._versions:
            if v.strategy_version_id == strategy_version_id:
                return v
        raise KeyError(strategy_version_id)

    def active(self) -> StrategyVersion | None:
        for v in self._versions:
            if v.status is StrategyVersionStatus.ACTIVE:
                return v
        return None

    def selectable_versions(self) -> "list[StrategyVersion]":
        """Versions a user may (re-)activate: APPLY_READY / PREVIOUS, never
        RETIRED, never the current ACTIVE."""
        return [
            v
            for v in self._versions
            if v.status in (StrategyVersionStatus.APPLY_READY, StrategyVersionStatus.PREVIOUS)
        ]

    # --- transitions ---------------------------------------------------
    def _replace(self, index: int, **changes) -> None:
        self._versions[index] = replace(self._versions[index], **changes)

    def mark_active(self, strategy_version_id: str, *, at: str) -> StrategyVersion:
        target_index = next(
            (i for i, v in enumerate(self._versions) if v.strategy_version_id == strategy_version_id),
            None,
        )
        if target_index is None:
            raise KeyError(strategy_version_id)
        if self._versions[target_index].status is StrategyVersionStatus.RETIRED:
            raise ValueError(f"{strategy_version_id} is RETIRED and cannot be activated")

        for i, v in enumerate(self._versions):
            if i == target_index:
                continue
            if v.status is StrategyVersionStatus.ACTIVE:
                self._replace(i, status=StrategyVersionStatus.PREVIOUS, deactivated_at=at)

        self._replace(
            target_index,
            status=StrategyVersionStatus.ACTIVE,
            activated_at=at,
            deactivated_at=None,
        )
        return self._versions[target_index]

    def mark_retired(self, strategy_version_id: str, *, at: str, reason: str) -> StrategyVersion:
        index = next(
            (i for i, v in enumerate(self._versions) if v.strategy_version_id == strategy_version_id),
            None,
        )
        if index is None:
            raise KeyError(strategy_version_id)
        self._replace(
            index,
            status=StrategyVersionStatus.RETIRED,
            retired_at=at,
            retired_reason=reason,
        )
        return self._versions[index]

    # --- serialization -----------------------------------------------
    def to_json(self) -> dict[str, object]:
        return {"versions": [v.to_json() for v in self._versions]}

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> "StrategyVersionRegistry":
        return cls([StrategyVersion.from_json(v) for v in (raw.get("versions") or [])])
