import sqlite3
import unittest
from types import SimpleNamespace
from gaon.control.passkey_strategy_begin import begin_strategy_approval
from gaon.control.passkey_strategy_finish import finish_strategy_approval
from gaon.control.passkey_repository import enroll_verified
from gaon.control.passkey_origin import RP_ID

class PasskeyStrategyFinishTests(unittest.TestCase):
    def test_bad_signature_consumes_challenge(self):
        c=sqlite3.connect(":memory:")
        enroll_verified(c,actor="owner",trusted_bootstrap=True,
            verified=SimpleNamespace(credential_id=b"credential",
              credential_public_key=b"public",sign_count=0,user_verified=True))
        args=dict(actor="owner",action="activate",family_id="family",
            version_id="v1",origin="https://"+RP_ID,request_host=RP_ID)
        begin_strategy_approval(c,**args)
        challenge=c.execute("SELECT challenge FROM gaon_passkey_challenges").fetchone()[0]
        with self.assertRaises(Exception):
            finish_strategy_approval(c,challenge=challenge,credential={},**args)
        self.assertEqual(c.execute("SELECT consumed FROM gaon_passkey_challenges").fetchone()[0],1)
        with self.assertRaisesRegex(PermissionError,"consumed"):
            finish_strategy_approval(c,challenge=challenge,credential={},**args)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM gaon_admin_passkeys").fetchone()[0],1)

    def test_cross_origin_does_not_consume_challenge(self):
        c=sqlite3.connect(":memory:")
        with self.assertRaisesRegex(PermissionError,"origin"):
            finish_strategy_approval(c,challenge=b"x",credential={},
              actor="owner",action="activate",family_id="f",version_id="v",
              origin="https://evil.example",request_host=RP_ID)

if __name__=="__main__": unittest.main()
