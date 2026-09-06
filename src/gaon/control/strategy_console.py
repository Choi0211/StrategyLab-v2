"""Priority 3 - the server-side read model behind the Web strategy console.

The Web proposal panel COLLAPSES / EXPANDS - it is never "dismissed"
(destroyed). Its open/closed state, and everything the console shows
(ACTIVE / APPLY_READY / PREVIOUS / RETIRED strategy versions, and which
of them can be applied or rolled back to), come from THIS backend read
model - not from web-local state - so a browser reload, or a second
browser, sees exactly the same thing.

Isolated: composes ``StrategyVersionRegistry`` (PR #204). No production
wiring, no deploy. The ``actions`` entries are affordance descriptors
the Web turns into buttons; pressing one is expected to call
``StrategyDeploymentController`` (PR #205), which owns the actual
lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from gaon.control.strategy_version import (
    StrategyVersion,
    StrategyVersionRegistry,
    StrategyVersionStatus,
)


@dataclass(frozen=True)
class ProposalPanelState:
    """Open/closed state of one proposal panel. ``collapsed=False`` (the
    default) means the panel is expanded / visible. There is deliberately
    no ``dismissed`` field: a proposal is never thrown away, only
    folded."""

    proposal_id: str
    collapsed: bool = False
    updated_at: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "collapsed": self.collapsed,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> "ProposalPanelState":
        return cls(
            proposal_id=str(raw["proposal_id"]),
            collapsed=bool(raw.get("collapsed", False)),
            updated_at=(str(raw["updated_at"]) if raw.get("updated_at") is not None else None),
        )


class ProposalPanelStore:
    """Server-side persistence for proposal-panel state, keyed by
    ``proposal_id``. Exposes only ``collapse`` / ``expand`` (both
    idempotent) and reads - never a ``dismiss`` / ``delete`` / ``purge``,
    so a panel can always be re-expanded after a reload."""

    def __init__(self, states: Mapping[str, ProposalPanelState] | None = None) -> None:
        self._states: dict[str, ProposalPanelState] = dict(states or {})

    def get(self, proposal_id: str) -> ProposalPanelState:
        return self._states.get(proposal_id, ProposalPanelState(proposal_id))

    def collapse(self, proposal_id: str, *, at: str) -> ProposalPanelState:
        return self._set(proposal_id, collapsed=True, at=at)

    def expand(self, proposal_id: str, *, at: str) -> ProposalPanelState:
        return self._set(proposal_id, collapsed=False, at=at)

    def _set(self, proposal_id: str, *, collapsed: bool, at: str) -> ProposalPanelState:
        current = self.get(proposal_id)
        updated = replace(current, collapsed=collapsed, updated_at=at)
        self._states[proposal_id] = updated
        return updated

    def to_json(self) -> dict[str, object]:
        return {"panels": [s.to_json() for s in self._states.values()]}

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> "ProposalPanelStore":
        panels = [ProposalPanelState.from_json(p) for p in (raw.get("panels") or [])]
        return cls({p.proposal_id: p for p in panels})


def _action_for(version: StrategyVersion) -> dict[str, object] | None:
    if version.status is StrategyVersionStatus.APPLY_READY:
        return {
            "strategy_version_id": version.strategy_version_id,
            "action": "apply",
            "label": f"Apply {version.spec_fingerprint}",
        }
    if version.status is StrategyVersionStatus.PREVIOUS:
        return {
            "strategy_version_id": version.strategy_version_id,
            "action": "rollback",
            "label": f"Roll back to {version.spec_fingerprint}",
        }
    return None  # ACTIVE and RETIRED are shown but not actionable


class StrategyConsoleReadModel:
    """Composes the version registry (and, optionally, a shared
    ``ProposalPanelStore``) into a single JSON-serializable view the Web
    strategy console renders."""

    def __init__(
        self,
        registry: StrategyVersionRegistry,
        *,
        panel_store: ProposalPanelStore | None = None,
    ) -> None:
        self._registry = registry
        self._panels = panel_store if panel_store is not None else ProposalPanelStore()

    # panel controls - thin pass-throughs so a caller with only the read
    # model can fold / unfold a panel against the shared store.
    def collapse_proposal(self, proposal_id: str, *, at: str) -> ProposalPanelState:
        return self._panels.collapse(proposal_id, at=at)

    def expand_proposal(self, proposal_id: str, *, at: str) -> ProposalPanelState:
        return self._panels.expand(proposal_id, at=at)

    def render(self, *, proposal_id: str | None = None) -> dict[str, object]:
        history = self._registry.history()
        by_status: dict[StrategyVersionStatus, list[dict[str, object]]] = {
            StrategyVersionStatus.APPLY_READY: [],
            StrategyVersionStatus.PREVIOUS: [],
            StrategyVersionStatus.RETIRED: [],
        }
        for version in history:
            if version.status in by_status:
                by_status[version.status].append(version.to_json())

        active = self._registry.active()
        actions = [a for a in (_action_for(v) for v in history) if a is not None]

        view: dict[str, object] = {
            "active": active.to_json() if active is not None else None,
            "apply_ready": by_status[StrategyVersionStatus.APPLY_READY],
            "previous": by_status[StrategyVersionStatus.PREVIOUS],
            "retired": by_status[StrategyVersionStatus.RETIRED],
            "actions": actions,
        }
        if proposal_id is not None:
            view["proposal_panel"] = self._panels.get(proposal_id).to_json()
        return view
