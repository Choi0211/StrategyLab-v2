"""Priority 1 / C4-C5 - the guarded mode-transition state machine.

Advances ONLY along the ordered path

  IDLE -> REQUESTED -> ENTRY_BLOCKED -> SOURCE_VERIFIED -> POSITIONS_VERIFIED
       -> SERVICE_STOPPED -> TARGET_VERIFIED -> SERVICE_STARTED
       -> EFFECTIVE_MODE_VERIFIED -> COMPLETE

and drops to FAILED_CLOSED on ANY step failure. FAILED_CLOSED is terminal
and leaves ``entry_blocked=True`` - there is no "auto continue trading"
branch out of a failed transition.

Service control goes through a ``ServiceManager`` interface - tests use
``FakeServiceManager`` only, never a real ``systemctl``. A real adapter
would implement the same three methods; it is intentionally not written
here.

DEMO -> LIVE is fail-closed in this module: it needs a transition-scoped
approval, which is a separate PR. LIVE -> DEMO and DEMO re-verification
run the full machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable

from gaon.control.trading_mode import (
    Mode,
    ServiceState,
    TradingModeControllerState,
    TransitionState,
)


class ServiceManager:
    """Interface: the three operations a mode transition needs. A real
    adapter (systemd, supervisor, ...) implements this; nothing here does."""

    def status(self) -> ServiceState:  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FakeServiceManager(ServiceManager):
    """In-memory ServiceManager for tests. ``fail_on`` ("stop" / "start")
    makes that call raise, to exercise the FAILED_CLOSED path."""

    def __init__(self, state: ServiceState = ServiceState.STOPPED, *, fail_on: str | None = None) -> None:
        self._state = state
        self._fail_on = fail_on
        self.calls: list[str] = []

    def status(self) -> ServiceState:
        return self._state

    def stop(self) -> None:
        self.calls.append("stop")
        if self._fail_on == "stop":
            raise RuntimeError("fake service manager: stop failed")
        self._state = ServiceState.STOPPED

    def start(self) -> None:
        self.calls.append("start")
        if self._fail_on == "start":
            raise RuntimeError("fake service manager: start failed")
        self._state = ServiceState.RUNNING


class TransitionOutcome(str, Enum):
    COMPLETE = "complete"
    FAILED_CLOSED = "failed_closed"


@dataclass
class TransitionResult:
    result: TransitionOutcome
    state: TradingModeControllerState
    visited: list[TransitionState] = field(default_factory=list)


def _profile_for(mode: Mode) -> str:
    return "live" if mode is Mode.LIVE else "demo"


class _StepFailure(Exception):
    def __init__(self, reason: str, *, effective_mode: Mode | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.effective_mode = effective_mode


class ModeTransition:
    """One attempt to move from ``start`` to ``target``. ``execute()`` is
    idempotent to construct-and-run; it never raises for a transition
    failure - it returns a FAILED_CLOSED result."""

    def __init__(
        self,
        *,
        start: TradingModeControllerState,
        target: Mode,
        service: ServiceManager,
        clock: Callable[[], str],
        verify_source_mode: Callable[[], Mode],
        verify_positions_safe: Callable[[], bool],
        verify_target_account: Callable[[str], bool],
        verify_effective_mode: Callable[[], Mode],
        live_approved: bool = False,
    ) -> None:
        self._start = start
        self._target = target
        self._service = service
        self._clock = clock
        self._verify_source_mode = verify_source_mode
        self._verify_positions_safe = verify_positions_safe
        self._verify_target_account = verify_target_account
        self._verify_effective_mode = verify_effective_mode
        self._live_approved = live_approved
        self._visited: list[TransitionState] = []

    def _advance(self, state: TradingModeControllerState, to: TransitionState) -> TradingModeControllerState:
        self._visited.append(to)
        return replace(state, transition_state=to)

    def execute(self) -> TransitionResult:
        state = replace(self._start, last_error=None)
        service_touched = False
        try:
            state = self._advance(state, TransitionState.REQUESTED)
            if self._target is Mode.LIVE and not self._live_approved:
                raise _StepFailure("DEMO->LIVE transition requires explicit transition-scoped approval")

            state = self._advance(state, TransitionState.ENTRY_BLOCKED)
            state = replace(state, entry_blocked=True)

            state = self._advance(state, TransitionState.SOURCE_VERIFIED)
            if self._verify_source_mode() is not self._start.effective_mode:
                raise _StepFailure("source mode verification mismatch")

            state = self._advance(state, TransitionState.POSITIONS_VERIFIED)
            if not self._verify_positions_safe():
                raise _StepFailure("open position ownership/protection not safe to transition")

            state = self._advance(state, TransitionState.SERVICE_STOPPED)
            service_touched = True
            self._service.stop()

            state = self._advance(state, TransitionState.TARGET_VERIFIED)
            if not self._verify_target_account(_profile_for(self._target)):
                raise _StepFailure("target account/credential-profile verification failed", effective_mode=Mode.UNKNOWN)

            state = self._advance(state, TransitionState.SERVICE_STARTED)
            self._service.start()

            state = self._advance(state, TransitionState.EFFECTIVE_MODE_VERIFIED)
            if self._verify_effective_mode() is not self._target:
                raise _StepFailure("effective mode after restart does not match target", effective_mode=Mode.UNKNOWN)

            state = self._advance(state, TransitionState.COMPLETE)
            state = replace(
                state,
                effective_mode=self._target,
                desired_mode=self._target,
                credential_profile=_profile_for(self._target),
                entry_blocked=False,
                last_verification=self._clock(),
                last_error=None,
            )
            return TransitionResult(TransitionOutcome.COMPLETE, state, list(self._visited))
        except _StepFailure as failure:
            # If we already stopped the service, try to bring it back up so
            # the box is not left dark - still FAILED_CLOSED, still no entries.
            if service_touched:
                try:
                    self._service.start()
                except Exception:  # noqa: BLE001 - best effort, stays fail-closed
                    pass
            effective = failure.effective_mode
            if effective is None:
                effective = Mode.UNKNOWN if service_touched else self._start.effective_mode
            state = self._advance(replace(state, last_error=None), TransitionState.FAILED_CLOSED)
            state = replace(
                state,
                transition_state=TransitionState.FAILED_CLOSED,
                effective_mode=effective,
                entry_blocked=True,
                last_error=failure.reason,
            )
            return TransitionResult(TransitionOutcome.FAILED_CLOSED, state, list(self._visited))
        except Exception as unexpected:  # noqa: BLE001 - service manager / verifier raised
            if service_touched:
                try:
                    self._service.start()
                except Exception:  # noqa: BLE001
                    pass
            state = self._advance(replace(state, last_error=None), TransitionState.FAILED_CLOSED)
            state = replace(
                state,
                transition_state=TransitionState.FAILED_CLOSED,
                effective_mode=Mode.UNKNOWN,
                entry_blocked=True,
                last_error=f"transition aborted: {type(unexpected).__name__}",
            )
            return TransitionResult(TransitionOutcome.FAILED_CLOSED, state, list(self._visited))
