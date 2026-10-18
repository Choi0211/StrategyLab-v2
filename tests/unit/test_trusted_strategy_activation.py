import unittest
from gaon.control.strategy_version import StrategyVersionRegistry
from gaon.control.trusted_strategy_activation import activate_approved_version
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository

T="2026-10-18T10:00:00Z"

class TrustedStrategyActivationTests(unittest.TestCase):
    def test_approval_consumed_and_rollback_preserves_history(self):
        store=RuntimeStateStore(":memory:")
        try:
            c=store._connection
            r=StrategyVersionRegistry()
            a=r.register_apply_ready(family_id="test",candidate_id="a",spec_fingerprint="a",
                spec_rules={},validation_summary={},at=T)
            b=r.register_apply_ready(family_id="test",candidate_id="b",spec_fingerprint="b",
                spec_rules={},validation_summary={},at=T)
            StrategyVersionSQLiteRepository(c).save("test",r,now=T)
            def approve(version,aid,**override):
                kwargs=dict(family_id="test",strategy_version_id=version,authenticated_actor="owner",
                    approval_id=aid,approved_family_id="test",approved_strategy_version_id=version,
                    approval_actor="owner",approved_at=T,expires_at="2026-10-18T12:00:00Z",
                    now="2026-10-18T11:00:00Z")
                kwargs.update(override)
                return activate_approved_version(c,**kwargs)
            with self.assertRaises(PermissionError):
                approve(a.strategy_version_id,"bad",approval_actor="other")
            self.assertTrue(approve(a.strategy_version_id,"1")["approval_consumed"])
            with self.assertRaises(PermissionError):
                approve(b.strategy_version_id,"1")
            approve(b.strategy_version_id,"2")
            self.assertEqual(StrategyVersionSQLiteRepository(c).get("test").get(a.strategy_version_id).status.value,"previous")
            approve(a.strategy_version_id,"3")
            final=StrategyVersionSQLiteRepository(c).get("test")
            self.assertEqual(final.active().strategy_version_id,a.strategy_version_id)
            self.assertEqual(len(final.history()),2)
            self.assertEqual(c.execute("SELECT count(*) FROM gaon_strategy_activation_audit").fetchone()[0],3)
        finally:
            store.close()

if __name__=="__main__": unittest.main()
