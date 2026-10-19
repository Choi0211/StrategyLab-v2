import sqlite3
import unittest
from types import SimpleNamespace
from gaon.control.passkey_strategy_begin import begin_strategy_approval
from gaon.control.passkey_repository import enroll_verified
from gaon.control.passkey_origin import RP_ID

class PasskeyStrategyBeginTests(unittest.TestCase):
    def test_begin_requires_registered_passkey(self):
        c=sqlite3.connect(":memory:")
        kw=dict(actor="owner",action="activate",family_id="f",version_id="v",
                origin="https://"+RP_ID,request_host=RP_ID)
        with self.assertRaisesRegex(PermissionError,"not registered"):
            begin_strategy_approval(c,**kw)
        enroll_verified(c,actor="owner",trusted_bootstrap=True,
            verified=SimpleNamespace(credential_id=b"credential",
                credential_public_key=b"public",sign_count=0,user_verified=True))
        options=begin_strategy_approval(c,**kw)
        self.assertIn('"challenge"',options)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM gaon_passkey_challenges").fetchone()[0],1)
        with self.assertRaisesRegex(PermissionError,"origin"):
            begin_strategy_approval(c,**{**kw,"origin":"https://evil.example"})
        with self.assertRaisesRegex(PermissionError,"action"):
            begin_strategy_approval(c,**{**kw,"action":"login"})

if __name__=="__main__": unittest.main()
