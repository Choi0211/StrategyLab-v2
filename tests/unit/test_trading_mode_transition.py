"""Priority 1 / C4-C5 - guarded mode transition state machine + FakeServiceManager.

The machine advances only along the exact ordered path
  IDLE -> REQUESTED -> ENTRY_BLOCKED -> SOURCE_VERIFIED -> POSITIONS_VERIFIED
       -> SERVICE_STOPPED -> TARGET_VERIFIED -> SERVICE_STARTED
       -> EFFECTIVE_MODE_VERIFIED -> COMPLETE
and drops to FAILED_CLOSED on ANY step failure. FAILED_CLOSED is terminal
and leaves entries blocked - never an "auto continue trading" path.

No real systemctl: tests use FakeServiceManager only.

DEMO->LIVE is fail-closed here (it needs an explicit approval mechanism,
a later PR); LIVE->DEMO / DEMO re-verification run the full machine.
"""

from __future__ import annotations

import unittest

from gaon.control.trading_mode import Mode, RiskGuardState, ServiceState, TradingModeControllerState, TransitionState
from gaon.control.transition import (
    FakeServiceManager,
    ModeTransition,
    TransitionOutcome,
)

AT = "2026-09-06T00:00:00Z"


def _live_state() -> TradingModeControllerState:
    return TradingModeControllerState(
        desired_mode=Mode.LIVE,
        effective_mode=Mode.LIVE,
        service_state=ServiceState.RUNNING,
        credential_profile="live",
        strategy_version="strategy-version:live-1",
        transition_state=TransitionState.IDLE,
        entry_blocked=False,
        risk_guard_state=RiskGuardState.OK,
        last_verification=AT,
        last_error=None,
    )


def _transition(target, *, state=None, service=None, **verifier_overrides):
    verifiers = dict(
        verify_source_mode=lambda: (state or _live_state()).effective_mode,
        verify_positions_safe=lambda: True,
        verify_target_account=lambda profile: True,
        verify_effective_mode=lambda: target,
    )
    verifiers.update(verifier_overrides)
    return ModeTransition(
        start=state or _live_state(),
        target=target,
        service=service or FakeServiceManager(ServiceState.RUNNING),
        clock=lambda: AT,
        **verifiers,
    )


class HappyPathLiveToDemoTests(unittest.TestCase):
    def test_full_ordered_path_reaches_complete(self) -> None:
        service = FakeServiceManager(ServiceState.RUNNING)
        run = _transition(Mode.DEMO, service=service)
        outcome = run.execute()
        self.assertEqual(outcome.result, TransitionOutcome.COMPLETE)
        self.assertEqual(outcome.state.transition_state, TransitionState.COMPLETE)
        self.assertIs(outcome.state.effective_mode, Mode.DEMO)
        self.assertEqual(
            outcome.visited,
            [
                TransitionState.REQUESTED,
                TransitionState.ENTRY_BLOCKED,
                TransitionState.SOURCE_VERIFIED,
                TransitionState.POSITIONS_VERIFIED,
                TransitionState.SERVICE_STOPPED,
                TransitionState.TARGET_VERIFIED,
                TransitionState.SERVICE_STARTED,
                TransitionState.EFFECTIVE_MODE_VERIFIED,
                TransitionState.COMPLETE,
            ],
        )
        # the service really was cycled.
        self.assertEqual(service.calls, ["stop", "start"])
        self.assertIs(service.status(), ServiceState.RUNNING)


class AnyStepFailureIsFailedClosedTests(unittest.TestCase):
    def test_positions_not_safe_fails_closed_before_the_service_is_touched(self) -> None:
        service = FakeServiceManager(ServiceState.RUNNING)
        run = _transition(Mode.DEMO, service=service, verify_positions_safe=lambda: False)
        outcome = run.execute()
        self.assertEqual(outcome.result, TransitionOutcome.FAILED_CLOSED)
        self.assertEqual(outcome.state.transition_state, TransitionState.FAILED_CLOSED)
        self.assertTrue(outcome.state.entry_blocked)
        self.assertIn("position", (outcome.state.last_error or "").lower())
        self.assertEqual(service.calls, [])  # never stopped/started

    def test_target_account_mismatch_fails_closed_and_restarts_the_service(self) -> None:
        service = FakeServiceManager(ServiceState.RUNNING)
        run = _transition(Mode.DEMO, service=service, verify_target_account=lambda profile: False)
        outcome = run.execute()
        self.assertEqual(outcome.result, TransitionOutcome.FAILED_CLOSED)
        # service was stopped, target failed -> it is brought back up, still fail-closed.
        self.assertIn("stop", service.calls)
        self.assertTrue(outcome.state.entry_blocked)
        self.assertIs(outcome.state.effective_mode, Mode.UNKNOWN)

    def test_effective_mode_mismatch_after_start_fails_closed(self) -> None:
        run = _transition(Mode.DEMO, verify_effective_mode=lambda: Mode.LIVE)
        outcome = run.execute()
        self.assertEqual(outcome.result, TransitionOutcome.FAILED_CLOSED)
        self.assertIn("effective", (outcome.state.last_error or "").lower())

    def test_service_manager_raising_fails_closed_not_propagates(self) -> None:
        service = FakeServiceManager(ServiceState.RUNNING, fail_on="stop")
        outcome = _transition(Mode.DEMO, service=service).execute()
        self.assertEqual(outcome.result, TransitionOutcome.FAILED_CLOSED)


class LiveTargetIsFailClosedPendingApprovalTests(unittest.TestCase):
    def test_demo_to_live_cannot_complete_here(self) -> None:
        state = TradingModeControllerState(
            desired_mode=Mode.LIVE, effective_mode=Mode.DEMO, service_state=ServiceState.RUNNING,
            credential_profile="demo", strategy_version=None, transition_state=TransitionState.IDLE,
            entry_blocked=False, risk_guard_state=RiskGuardState.OK, last_verification=AT, last_error=None,
        )
        outcome = _transition(Mode.LIVE, state=state).execute()
        self.assertEqual(outcome.result, TransitionOutcome.FAILED_CLOSED)
        self.assertIn("approval", (outcome.state.last_error or "").lower())
        self.assertEqual(outcome.state.transition_state, TransitionState.FAILED_CLOSED)


class FakeServiceManagerTests(unittest.TestCase):
    def test_stop_start_status(self) -> None:
        s = FakeServiceManager(ServiceState.RUNNING)
        s.stop()
        self.assertIs(s.status(), ServiceState.STOPPED)
        s.start()
        self.assertIs(s.status(), ServiceState.RUNNING)
        self.assertEqual(s.calls, ["stop", "start"])

    def test_configured_failure_raises(self) -> None:
        s = FakeServiceManager(ServiceState.RUNNING, fail_on="start")
        with self.assertRaises(RuntimeError):
            s.start()


if __name__ == "__main__":
    unittest.main()
