"""Priority 1 / C1-C2 - the canonical TradingModeController and its state.

ISOLATED development module - nothing in the runtime imports it yet. It
exists so that Web, Gaon and the Binance bot can, in a later wiring step,
read ONE mode read model instead of each keeping their own mode fields.

Design invariants:
  - ``effective_mode`` is what has actually been OBSERVED/verified, never
    what someone asked for. Until a verification is recorded it is
    ``Mode.UNKNOWN``.
  - ``Mode.UNKNOWN`` (or a ``FAILED_CLOSED`` transition, or a triggered
    risk guard, or an explicit entry block) means: no entries. Fail
    closed.
  - There is no ``set_mode(LIVE)`` shortcut here - a DEMO -> LIVE change
    goes through an explicit, transition-scoped approval (a later module).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Mode(str, Enum):
    DEMO = "demo"
    LIVE = "live"
    UNKNOWN = "unknown"


class ServiceState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class RiskGuardState(str, Enum):
    OK = "ok"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"


class TransitionState(str, Enum):
    IDLE = "idle"
    REQUESTED = "requested"
    ENTRY_BLOCKED = "entry_blocked"
    SOURCE_VERIFIED = "source_verified"
    POSITIONS_VERIFIED = "positions_verified"
    SERVICE_STOPPED = "service_stopped"
    TARGET_VERIFIED = "target_verified"
    SERVICE_STARTED = "service_started"
    EFFECTIVE_MODE_VERIFIED = "effective_mode_verified"
    COMPLETE = "complete"
    FAILED_CLOSED = "failed_closed"


@dataclass(frozen=True)
class TradingModeControllerState:
    """The single source of truth. Every consumer reads this - none keeps
    its own copy of ``mode``."""

    desired_mode: Mode
    effective_mode: Mode
    service_state: ServiceState
    credential_profile: str
    strategy_version: str | None
    transition_state: TransitionState
    entry_blocked: bool
    risk_guard_state: RiskGuardState
    last_verification: str | None
    last_error: str | None

    @property
    def is_fail_closed(self) -> bool:
        return (
            self.effective_mode is Mode.UNKNOWN
            or self.transition_state is TransitionState.FAILED_CLOSED
        )

    @property
    def entry_allowed(self) -> bool:
        """Entries are allowed ONLY when every safe condition holds: a
        known effective mode, not fail-closed, no explicit entry block,
        risk guard OK. Anything ambiguous -> False."""
        return not (
            self.entry_blocked
            or self.is_fail_closed
            or self.effective_mode is Mode.UNKNOWN
            or self.risk_guard_state is not RiskGuardState.OK
        )

    def to_json(self) -> dict[str, object]:
        return {
            "desired_mode": self.desired_mode.value,
            "effective_mode": self.effective_mode.value,
            "service_state": self.service_state.value,
            "credential_profile": self.credential_profile,
            "strategy_version": self.strategy_version,
            "transition_state": self.transition_state.value,
            "entry_blocked": self.entry_blocked,
            "risk_guard_state": self.risk_guard_state.value,
            "last_verification": self.last_verification,
            "last_error": self.last_error,
        }

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> "TradingModeControllerState":
        return cls(
            desired_mode=Mode(str(raw["desired_mode"])),
            effective_mode=Mode(str(raw["effective_mode"])),
            service_state=ServiceState(str(raw["service_state"])),
            credential_profile=str(raw["credential_profile"]),
            strategy_version=(str(raw["strategy_version"]) if raw.get("strategy_version") is not None else None),
            transition_state=TransitionState(str(raw["transition_state"])),
            entry_blocked=bool(raw["entry_blocked"]),
            risk_guard_state=RiskGuardState(str(raw["risk_guard_state"])),
            last_verification=(str(raw["last_verification"]) if raw.get("last_verification") is not None else None),
            last_error=(str(raw["last_error"]) if raw.get("last_error") is not None else None),
        )

    @classmethod
    def unknown(cls, *, desired_mode: Mode = Mode.DEMO, credential_profile: str = "unknown") -> "TradingModeControllerState":
        """A fresh, nothing-verified-yet state: fail closed on every axis."""
        return cls(
            desired_mode=desired_mode,
            effective_mode=Mode.UNKNOWN,
            service_state=ServiceState.UNKNOWN,
            credential_profile=credential_profile,
            strategy_version=None,
            transition_state=TransitionState.IDLE,
            entry_blocked=True,
            risk_guard_state=RiskGuardState.UNKNOWN,
            last_verification=None,
            last_error=None,
        )


class TradingModeController:
    """Owns exactly one ``TradingModeControllerState``. ``read_model()`` is
    the only way to obtain mode state anywhere in the system."""

    def __init__(self, state: TradingModeControllerState | None = None) -> None:
        self._state = state or TradingModeControllerState.unknown()

    def read_model(self) -> TradingModeControllerState:
        return self._state

    def record_verification(
        self,
        *,
        effective_mode: Mode,
        service_state: ServiceState,
        risk_guard_state: RiskGuardState,
        at: str,
        strategy_version: str | None = None,
        credential_profile: str | None = None,
    ) -> TradingModeControllerState:
        """Fold an OBSERVED truth (what the running service actually is)
        into the canonical state. An UNKNOWN observation is honestly
        recorded - it returns the controller to fail-closed rather than
        keeping a stale 'known' value."""
        self._state = replace(
            self._state,
            effective_mode=effective_mode,
            service_state=service_state,
            risk_guard_state=risk_guard_state,
            last_verification=at,
            strategy_version=strategy_version if strategy_version is not None else self._state.strategy_version,
            credential_profile=credential_profile if credential_profile is not None else self._state.credential_profile,
        )
        return self._state
