"""Priority 1 / C1-C2 - canonical TradingModeController + Mode.

An ISOLATED development module (gaon.control.trading_mode) with no
production wiring. It is the single source of truth for the bot's mode
state: Web, Gaon and the Binance bot all read this one read model rather
than keeping their own mode fields.

Fail-closed invariants proven here:
  - a fresh controller (nothing verified yet) is UNKNOWN and blocks entry;
  - effective_mode == UNKNOWN always blocks entry, regardless of other
    fields;
  - transition_state == FAILED_CLOSED blocks entry;
  - risk_guard_state == TRIGGERED blocks entry;
  - the state round-trips through JSON unchanged.
"""

from __future__ import annotations

import unittest

from gaon.control.trading_mode import (
    Mode,
    RiskGuardState,
    ServiceState,
    TradingModeController,
    TradingModeControllerState,
    TransitionState,
)

AT = "2026-09-06T00:00:00Z"


class ModeEnumTests(unittest.TestCase):
    def test_mode_has_demo_live_unknown(self) -> None:
        self.assertEqual({m.value for m in Mode}, {"demo", "live", "unknown"})


class FreshControllerIsUnknownAndFailClosedTests(unittest.TestCase):
    def test_new_controller_reads_unknown_and_blocks_entry(self) -> None:
        controller = TradingModeController()
        state = controller.read_model()
        self.assertIs(state.effective_mode, Mode.UNKNOWN)
        self.assertIs(state.transition_state, TransitionState.IDLE)
        self.assertTrue(state.entry_blocked)
        self.assertFalse(state.entry_allowed)
        self.assertTrue(state.is_fail_closed)

    def test_read_model_is_the_only_mode_state_and_is_immutable(self) -> None:
        controller = TradingModeController()
        a = controller.read_model()
        b = controller.read_model()
        self.assertEqual(a, b)
        with self.assertRaises(Exception):
            a.effective_mode = Mode.LIVE  # frozen dataclass


class EntryAllowedRequiresEverySafeConditionTests(unittest.TestCase):
    def _verified(self, **overrides) -> TradingModeControllerState:
        base = dict(
            desired_mode=Mode.DEMO,
            effective_mode=Mode.DEMO,
            service_state=ServiceState.RUNNING,
            credential_profile="demo",
            strategy_version="strategy-version:demo-1",
            transition_state=TransitionState.COMPLETE,
            entry_blocked=False,
            risk_guard_state=RiskGuardState.OK,
            last_verification=AT,
            last_error=None,
        )
        base.update(overrides)
        return TradingModeControllerState(**base)

    def test_a_fully_verified_demo_state_allows_entry(self) -> None:
        self.assertTrue(self._verified().entry_allowed)

    def test_unknown_effective_mode_blocks_entry(self) -> None:
        self.assertFalse(self._verified(effective_mode=Mode.UNKNOWN).entry_allowed)

    def test_failed_closed_transition_blocks_entry(self) -> None:
        self.assertFalse(self._verified(transition_state=TransitionState.FAILED_CLOSED).entry_allowed)

    def test_risk_guard_triggered_blocks_entry(self) -> None:
        self.assertFalse(self._verified(risk_guard_state=RiskGuardState.TRIGGERED).entry_allowed)

    def test_explicit_entry_block_blocks_entry(self) -> None:
        self.assertFalse(self._verified(entry_blocked=True).entry_allowed)


class RecordVerificationUpdatesTheCanonicalStateTests(unittest.TestCase):
    def test_recording_an_observed_demo_truth_clears_unknown(self) -> None:
        controller = TradingModeController()
        controller.record_verification(
            effective_mode=Mode.DEMO,
            service_state=ServiceState.RUNNING,
            risk_guard_state=RiskGuardState.OK,
            at=AT,
        )
        state = controller.read_model()
        self.assertIs(state.effective_mode, Mode.DEMO)
        self.assertEqual(state.last_verification, AT)
        self.assertFalse(state.is_fail_closed)

    def test_recording_an_unknown_observation_returns_to_fail_closed(self) -> None:
        controller = TradingModeController()
        controller.record_verification(effective_mode=Mode.DEMO, service_state=ServiceState.RUNNING, risk_guard_state=RiskGuardState.OK, at=AT)
        controller.record_verification(effective_mode=Mode.UNKNOWN, service_state=ServiceState.UNKNOWN, risk_guard_state=RiskGuardState.UNKNOWN, at="2026-09-06T01:00:00Z")
        self.assertTrue(controller.read_model().is_fail_closed)
        self.assertFalse(controller.read_model().entry_allowed)


class StateJsonRoundTripTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        controller = TradingModeController()
        controller.record_verification(effective_mode=Mode.LIVE, service_state=ServiceState.RUNNING, risk_guard_state=RiskGuardState.OK, at=AT)
        state = controller.read_model()
        again = TradingModeControllerState.from_json(state.to_json())
        self.assertEqual(state, again)


if __name__ == "__main__":
    unittest.main()
