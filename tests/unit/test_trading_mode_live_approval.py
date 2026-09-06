"""Priority 1 / C6 - explicit DEMO -> LIVE approval.

The single most important invariant: nothing turns the bot LIVE without
a transition-scoped approval. There is no set_mode(LIVE) / force-live
call anywhere in gaon.control.

An approval is a one-shot ticket for ONE specific (from_mode, to_mode,
intent). Validation fails closed for: no approval, expired, wrong
transition, wrong intent, already consumed.
"""

from __future__ import annotations

import unittest

from gaon.control import approval as approval_module
from gaon.control.approval import (
    ApprovalError,
    ApprovalRegistry,
    LIVE_TRANSITION_INTENT,
    require_live_approval,
)
from gaon.control.trading_mode import (
    Mode,
    RiskGuardState,
    ServiceState,
    TradingModeControllerState,
    TransitionState,
)
from gaon.control.transition import FakeServiceManager, ModeTransition, TransitionOutcome

T0 = "2026-09-06T00:00:00Z"
T_5MIN = "2026-09-06T00:05:00Z"
T_2H = "2026-09-06T02:00:00Z"
INTENT = "demo_to_live"


class NoForceLiveApiExistsTests(unittest.TestCase):
    def test_module_exposes_no_set_mode_or_force_live(self) -> None:
        names = set(dir(approval_module))
        for banned in ("set_mode", "force_live", "force_mode", "make_live", "activate_live"):
            self.assertNotIn(banned, names)


class RequireLiveApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = ApprovalRegistry()

    def test_no_approval_is_denied(self) -> None:
        self.assertFalse(require_live_approval(self.reg, "does-not-exist", now=T_5MIN))

    def test_valid_unexpired_matching_approval_is_allowed_exactly_once(self) -> None:
        ticket = self.reg.issue(Mode.DEMO, Mode.LIVE, INTENT, now=T0, ttl_seconds=1800, issued_by="owner")
        self.assertTrue(require_live_approval(self.reg, ticket.approval_id, now=T_5MIN))
        # consumed - a second use is denied.
        self.assertFalse(require_live_approval(self.reg, ticket.approval_id, now=T_5MIN))

    def test_expired_approval_is_denied(self) -> None:
        ticket = self.reg.issue(Mode.DEMO, Mode.LIVE, INTENT, now=T0, ttl_seconds=1800, issued_by="owner")
        self.assertFalse(require_live_approval(self.reg, ticket.approval_id, now=T_2H))

    def test_approval_for_a_different_transition_is_denied(self) -> None:
        ticket = self.reg.issue(Mode.LIVE, Mode.DEMO, "live_to_demo", now=T0, ttl_seconds=1800, issued_by="owner")
        self.assertFalse(require_live_approval(self.reg, ticket.approval_id, now=T_5MIN))

    def test_approval_with_a_different_intent_is_denied(self) -> None:
        ticket = self.reg.issue(Mode.DEMO, Mode.LIVE, "some_other_intent", now=T0, ttl_seconds=1800, issued_by="owner")
        self.assertFalse(require_live_approval(self.reg, ticket.approval_id, now=T_5MIN))


class ValidateAndConsumeRaisesTypedErrorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = ApprovalRegistry()

    def _issue(self, frm=Mode.DEMO, to=Mode.LIVE, intent=INTENT):
        return self.reg.issue(frm, to, intent, now=T0, ttl_seconds=1800, issued_by="owner")

    def test_unknown_id(self) -> None:
        with self.assertRaises(ApprovalError) as ctx:
            self.reg.validate_and_consume("nope", Mode.DEMO, Mode.LIVE, INTENT, now=T_5MIN)
        self.assertEqual(ctx.exception.reason, "no_approval")

    def test_stale(self) -> None:
        t = self._issue()
        with self.assertRaises(ApprovalError) as ctx:
            self.reg.validate_and_consume(t.approval_id, Mode.DEMO, Mode.LIVE, INTENT, now=T_2H)
        self.assertEqual(ctx.exception.reason, "stale")

    def test_wrong_transition(self) -> None:
        t = self._issue()
        with self.assertRaises(ApprovalError) as ctx:
            self.reg.validate_and_consume(t.approval_id, Mode.LIVE, Mode.DEMO, INTENT, now=T_5MIN)
        self.assertEqual(ctx.exception.reason, "wrong_transition")

    def test_wrong_intent(self) -> None:
        t = self._issue()
        with self.assertRaises(ApprovalError) as ctx:
            self.reg.validate_and_consume(t.approval_id, Mode.DEMO, Mode.LIVE, "mismatch", now=T_5MIN)
        self.assertEqual(ctx.exception.reason, "wrong_intent")

    def test_already_consumed(self) -> None:
        t = self._issue()
        self.reg.validate_and_consume(t.approval_id, Mode.DEMO, Mode.LIVE, INTENT, now=T_5MIN)
        with self.assertRaises(ApprovalError) as ctx:
            self.reg.validate_and_consume(t.approval_id, Mode.DEMO, Mode.LIVE, INTENT, now=T_5MIN)
        self.assertEqual(ctx.exception.reason, "already_consumed")

    def test_happy_path_returns_the_ticket_and_marks_consumed(self) -> None:
        t = self._issue()
        got = self.reg.validate_and_consume(t.approval_id, Mode.DEMO, Mode.LIVE, INTENT, now=T_5MIN)
        self.assertEqual(got.approval_id, t.approval_id)
        self.assertTrue(self.reg.is_consumed(t.approval_id))


def _demo_state() -> TradingModeControllerState:
    return TradingModeControllerState(
        desired_mode=Mode.LIVE, effective_mode=Mode.DEMO, service_state=ServiceState.RUNNING,
        credential_profile="demo", strategy_version=None, transition_state=TransitionState.IDLE,
        entry_blocked=False, risk_guard_state=RiskGuardState.OK, last_verification=T0, last_error=None,
    )


def _live_transition(*, registry=None, approval_id=None, live_approved=False):
    return ModeTransition(
        start=_demo_state(),
        target=Mode.LIVE,
        service=FakeServiceManager(ServiceState.RUNNING),
        clock=lambda: T_5MIN,
        verify_source_mode=lambda: Mode.DEMO,
        verify_positions_safe=lambda: True,
        verify_target_account=lambda profile: True,
        verify_effective_mode=lambda: Mode.LIVE,
        live_approved=live_approved,
        approval_registry=registry,
        approval_id=approval_id,
    )


class ModeTransitionConsumesTheApprovalTests(unittest.TestCase):
    def test_demo_to_live_completes_with_a_valid_one_shot_approval_and_then_cannot_be_reused(self) -> None:
        reg = ApprovalRegistry()
        ticket = reg.issue(Mode.DEMO, Mode.LIVE, LIVE_TRANSITION_INTENT, now=T0, ttl_seconds=1800, issued_by="owner")
        outcome = _live_transition(registry=reg, approval_id=ticket.approval_id).execute()
        self.assertEqual(outcome.result, TransitionOutcome.COMPLETE)
        self.assertIs(outcome.state.effective_mode, Mode.LIVE)
        self.assertTrue(reg.is_consumed(ticket.approval_id))
        # a second transition attempt with the same (now consumed) ticket fails closed.
        again = _live_transition(registry=reg, approval_id=ticket.approval_id).execute()
        self.assertEqual(again.result, TransitionOutcome.FAILED_CLOSED)

    def test_demo_to_live_without_a_registry_fails_closed(self) -> None:
        self.assertEqual(_live_transition().execute().result, TransitionOutcome.FAILED_CLOSED)

    def test_demo_to_live_with_a_stale_approval_fails_closed(self) -> None:
        reg = ApprovalRegistry()
        ticket = reg.issue(Mode.DEMO, Mode.LIVE, LIVE_TRANSITION_INTENT, now="2026-09-05T00:00:00Z", ttl_seconds=60, issued_by="owner")
        self.assertEqual(_live_transition(registry=reg, approval_id=ticket.approval_id).execute().result, TransitionOutcome.FAILED_CLOSED)

    def test_demo_to_live_with_a_wrong_transition_approval_fails_closed(self) -> None:
        reg = ApprovalRegistry()
        ticket = reg.issue(Mode.LIVE, Mode.DEMO, "live_to_demo", now=T0, ttl_seconds=1800, issued_by="owner")
        self.assertEqual(_live_transition(registry=reg, approval_id=ticket.approval_id).execute().result, TransitionOutcome.FAILED_CLOSED)


if __name__ == "__main__":
    unittest.main()
