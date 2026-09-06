"""Priority 2 / D2 + D3 - one-click safe apply + rollback lifecycle.

The Web [apply] / [rollback to this] button does NOT touch
systemctl/config directly - it asks a StrategyDeploymentController, which
runs one bounded lifecycle:

  REQUESTED -> VALIDATED -> ENTRY_BLOCKED -> RUNTIME_PRECONDITIONS_OK
  -> VERSION_APPLIED -> EFFECTIVE_VERSION_VERIFIED -> ACTIVE

and drops to FAILED_CLOSED on ANY step failure. The invariant this suite
exists for: a mid-transition failure NEVER loses the strategy that was
ACTIVE - the registry's ACTIVE pointer only moves at the last step, and
the runtime is best-effort restored to the previous version.

Rollback is the SAME lifecycle with a PREVIOUS version as the target.

Isolated module - FakeStrategyRuntime only, no real systemctl/config.
"""

from __future__ import annotations

import unittest

from gaon.control.strategy_deployment import (
    DeployOutcome,
    FakeStrategyRuntime,
    StrategyDeploymentController,
)
from gaon.control.strategy_version import StrategyVersionRegistry, StrategyVersionStatus


def _reg_with(*fingerprints):
    reg = StrategyVersionRegistry()
    ids = []
    for i, fp in enumerate(fingerprints):
        v = reg.register_apply_ready(
            family_id="mean_reversion_standard",
            candidate_id=f"KR-ST-{10 + i:03d}",
            spec_fingerprint=fp,
            spec_rules={"entry": {"mean_reversion_ma_lookback": {"value": 20}}, "fp": fp},
            validation_summary={"trade_count": 40, "status": "pass"},
            at=f"2026-09-06T0{i}:00:00Z",
        )
        ids.append(v.strategy_version_id)
    return reg, ids


class HappyPathApplyTests(unittest.TestCase):
    def test_apply_runs_the_full_lifecycle_and_makes_the_version_active(self) -> None:
        reg, [va] = _reg_with("fp-a")
        runtime = FakeStrategyRuntime(effective="fp-none")
        ctrl = StrategyDeploymentController(reg, runtime)
        outcome = ctrl.request_apply(va, at="2026-09-06T10:00:00Z")
        self.assertEqual(outcome.result, DeployOutcome.ACTIVE)
        self.assertEqual(reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(runtime.effective_fingerprint(), "fp-a")
        self.assertFalse(runtime.entries_blocked)  # unblocked on success
        self.assertIn("EFFECTIVE_VERSION_VERIFIED", [s.name for s in outcome.steps])

    def test_apply_then_apply_b_then_rollback_to_a(self) -> None:
        reg, [va, vb] = _reg_with("fp-a", "fp-b")
        runtime = FakeStrategyRuntime(effective="fp-none")
        ctrl = StrategyDeploymentController(reg, runtime)
        ctrl.request_apply(va, at="2026-09-06T10:00:00Z")
        ctrl.request_apply(vb, at="2026-09-06T11:00:00Z")
        self.assertEqual(reg.active().spec_fingerprint, "fp-b")
        out = ctrl.request_rollback(va, at="2026-09-06T12:00:00Z")
        self.assertEqual(out.result, DeployOutcome.ACTIVE)
        self.assertEqual(reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(runtime.effective_fingerprint(), "fp-a")
        self.assertEqual(reg.get(vb).status, StrategyVersionStatus.PREVIOUS)


class FailureNeverLosesTheActiveVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg, [self.va, self.vb] = _reg_with("fp-a", "fp-b")
        self.runtime = FakeStrategyRuntime(effective="fp-none")
        self.ctrl = StrategyDeploymentController(self.reg, self.runtime)
        self.ctrl.request_apply(self.va, at="2026-09-06T10:00:00Z")
        assert self.reg.active().spec_fingerprint == "fp-a"

    def test_validation_failure_keeps_a_active_and_never_touches_the_runtime(self) -> None:
        out = self.ctrl.request_apply(self.vb, at="2026-09-06T11:00:00Z", validate=lambda v: False)
        self.assertEqual(out.result, DeployOutcome.FAILED_CLOSED)
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(self.runtime.effective_fingerprint(), "fp-a")
        self.assertEqual(self.reg.get(self.vb).status, StrategyVersionStatus.APPLY_READY)

    def test_precondition_failure_keeps_a_active(self) -> None:
        out = self.ctrl.request_apply(self.vb, at="2026-09-06T11:00:00Z", precheck=lambda: False)
        self.assertEqual(out.result, DeployOutcome.FAILED_CLOSED)
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")

    def test_runtime_apply_raising_restores_a_and_keeps_it_active(self) -> None:
        self.runtime.fail_on = "apply"
        out = self.ctrl.request_apply(self.vb, at="2026-09-06T11:00:00Z")
        self.assertEqual(out.result, DeployOutcome.FAILED_CLOSED)
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")
        # best-effort restore of the runtime to the previous version.
        self.assertEqual(self.runtime.effective_fingerprint(), "fp-a")
        self.assertTrue(self.runtime.entries_blocked)  # stays blocked on failure

    def test_effective_verify_mismatch_keeps_a_active(self) -> None:
        self.runtime.fail_on = "verify"  # the post-apply verification read reports drift
        out = self.ctrl.request_apply(self.vb, at="2026-09-06T11:00:00Z")
        self.assertEqual(out.result, DeployOutcome.FAILED_CLOSED)
        self.assertEqual(out.last_error, "effective runtime fingerprint does not match the target version")
        # the registry ACTIVE pointer never moved - A is still ACTIVE.
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(self.reg.get(self.vb).status, StrategyVersionStatus.APPLY_READY)

    def test_rollback_failure_leaves_current_active_unchanged(self) -> None:
        self.ctrl.request_apply(self.vb, at="2026-09-06T11:00:00Z")  # b active
        self.runtime.fail_on = "apply"
        out = self.ctrl.request_rollback(self.va, at="2026-09-06T12:00:00Z")
        self.assertEqual(out.result, DeployOutcome.FAILED_CLOSED)
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-b")


class NoDirectSystemMutationTests(unittest.TestCase):
    def test_module_exposes_no_systemctl_or_config_write(self) -> None:
        import gaon.control.strategy_deployment as m

        for banned in ("systemctl", "restart_service", "write_config", "apply_to_production", "deploy"):
            self.assertNotIn(banned, set(dir(m)))


if __name__ == "__main__":
    unittest.main()
