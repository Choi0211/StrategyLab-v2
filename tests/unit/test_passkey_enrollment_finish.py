import sqlite3
import unittest
from gaon.control.passkey_enrollment_finish import finish_trusted_enrollment
from gaon.control.passkey_origin import RP_ID

class PasskeyEnrollmentFinishTests(unittest.TestCase):
    def test_rejects_missing_client_data(self):
        c=sqlite3.connect(":memory:")
        with self.assertRaisesRegex(PermissionError,"missing client"):
            finish_trusted_enrollment(c,actor="owner",credential={"response":{}},
                origin="https://"+RP_ID,request_host=RP_ID)

    def test_rejects_untrusted_origin_before_credential(self):
        c=sqlite3.connect(":memory:")
        with self.assertRaisesRegex(PermissionError,"origin"):
            finish_trusted_enrollment(c,actor="owner",credential={},
                origin="https://evil.example",request_host=RP_ID)

if __name__=="__main__": unittest.main()
