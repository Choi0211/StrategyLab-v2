import sqlite3
import unittest
from gaon.control.passkey_bootstrap import create_local_grant
from gaon.control.passkey_enrollment_store import begin_trusted_enrollment,consume_enrollment
from gaon.control.passkey_origin import RP_ID

class PasskeyEnrollmentStoreTests(unittest.TestCase):
    def test_trusted_enrollment_consumes_both_tokens(self):
        c=sqlite3.connect(":memory:")
        token=create_local_grant(c,actor="owner")
        kw=dict(actor="owner",token=token,origin="https://"+RP_ID,request_host=RP_ID)
        options=begin_trusted_enrollment(c,**kw)
        self.assertIn('"challenge"',options)
        with self.assertRaises(PermissionError):
            begin_trusted_enrollment(c,**kw)
        challenge=c.execute("SELECT challenge FROM gaon_passkey_enrollments").fetchone()[0]
        self.assertEqual(consume_enrollment(c,challenge=challenge,actor="owner").actor,"owner")
        with self.assertRaises(PermissionError):
            consume_enrollment(c,challenge=challenge,actor="owner")

    def test_cross_origin_does_not_consume_bootstrap(self):
        c=sqlite3.connect(":memory:")
        token=create_local_grant(c,actor="owner")
        with self.assertRaises(PermissionError):
            begin_trusted_enrollment(c,actor="owner",token=token,
                origin="https://evil.example",request_host=RP_ID)
        self.assertTrue(begin_trusted_enrollment(c,actor="owner",token=token,
                origin="https://"+RP_ID,request_host=RP_ID))

if __name__=="__main__": unittest.main()
