import unittest
from gaon.control.passkey_strategy_approval import approve_with_passkey
from gaon.runtime.storage import RuntimeStateStore

class PasskeyStrategyApprovalTests(unittest.TestCase):
    def test_no_registered_passkey_cannot_activate(self):
        store=RuntimeStateStore(":memory:")
        try:
            with self.assertRaisesRegex(PermissionError,"registered"):
                approve_with_passkey(store._connection,pending=None,credential={},
                    actor="owner",action="activate",family_id="test",
                    strategy_version_id="v1",rp_id="example.com",
                    origin="https://example.com")
        finally:
            store.close()

    def test_invalid_action_cannot_activate(self):
        store=RuntimeStateStore(":memory:")
        try:
            with self.assertRaisesRegex(PermissionError,"action"):
                approve_with_passkey(store._connection,pending=None,credential={},
                    actor="owner",action="login",family_id="test",
                    strategy_version_id="v1",rp_id="example.com",
                    origin="https://example.com")
        finally:
            store.close()

if __name__=="__main__": unittest.main()
