import sqlite3
import unittest
from types import SimpleNamespace
from gaon.control.passkey_readiness import readiness
from gaon.control.passkey_repository import enroll_verified
from gaon.control.passkey_origin import RP_ID

class PasskeyReadinessTests(unittest.TestCase):
    def test_readiness_never_exposes_passkey_or_claims_approval(self):
        c=sqlite3.connect(":memory:")
        first=readiness(c)
        self.assertEqual(first["passkey_rp_id"],RP_ID)
        self.assertFalse(first["registration_complete"])
        enroll_verified(c,actor="owner",trusted_bootstrap=True,
          verified=SimpleNamespace(credential_id=b"secret-id",
            credential_public_key=b"public-key",sign_count=0,user_verified=True))
        after=readiness(c)
        self.assertTrue(after["registration_complete"])
        self.assertFalse(after["admin_login_enabled"])
        self.assertFalse(after["strategy_approval_enabled"])
        self.assertNotIn("secret-id",str(after))
        self.assertNotIn("owner",str(after))

if __name__=="__main__": unittest.main()
