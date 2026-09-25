import unittest
from gaon.control.strategy_deployment import FakeStrategyRuntime, StrategyDeploymentController, DeployOutcome
from gaon.control.strategy_version import StrategyVersionRegistry

class DirectionalDeploymentIsolationTests(unittest.TestCase):
    def _reg(self):
        r=StrategyVersionRegistry()
        l1=r.register_apply_ready(family_id='f',candidate_id='l1',spec_fingerprint='fp-l1',spec_rules={},validation_summary={},at='2026-09-01T00:00:00Z',direction='LONG')
        s1=r.register_apply_ready(family_id='f',candidate_id='s1',spec_fingerprint='fp-s1',spec_rules={},validation_summary={},at='2026-09-01T00:00:01Z',direction='SHORT')
        r.mark_active(l1.strategy_version_id,at='2026-09-01T00:01:00Z'); r.mark_active(s1.strategy_version_id,at='2026-09-01T00:01:01Z')
        return r,l1,s1
    def test_long_activation_preserves_short_active(self):
        r,l1,s1=self._reg(); l2=r.register_apply_ready(family_id='f',candidate_id='l2',spec_fingerprint='fp-l2',spec_rules={},validation_summary={},at='2026-09-02T00:00:00Z',direction='LONG')
        rt=FakeStrategyRuntime(effective='fp-l1'); out=StrategyDeploymentController(r,rt).request_apply(l2.strategy_version_id,at='2026-09-02T00:01:00Z')
        self.assertEqual(out.result,DeployOutcome.ACTIVE); self.assertEqual(r.active('LONG').strategy_version_id,l2.strategy_version_id); self.assertEqual(r.active('SHORT').strategy_version_id,s1.strategy_version_id)
    def test_failed_long_apply_reports_and_restores_long_not_short(self):
        r,l1,s1=self._reg(); l2=r.register_apply_ready(family_id='f',candidate_id='l2',spec_fingerprint='fp-l2',spec_rules={},validation_summary={},at='2026-09-02T00:00:00Z',direction='LONG')
        rt=FakeStrategyRuntime(effective='fp-l1'); rt.fail_on='verify'; out=StrategyDeploymentController(r,rt).request_apply(l2.strategy_version_id,at='2026-09-02T00:01:00Z')
        self.assertEqual(out.result,DeployOutcome.FAILED_CLOSED); self.assertEqual(out.active_version_id,l1.strategy_version_id); self.assertEqual(r.active('LONG').strategy_version_id,l1.strategy_version_id); self.assertEqual(r.active('SHORT').strategy_version_id,s1.strategy_version_id)
