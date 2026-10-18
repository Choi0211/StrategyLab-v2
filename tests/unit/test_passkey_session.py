import sqlite3
import unittest
from datetime import datetime,timezone,timedelta
from gaon.control.passkey_session import create_session,validate_session,revoke_session

class PasskeySessionTests(unittest.TestCase):
    def test_requires_verified_login(self):
        c=sqlite3.connect(":memory:")
        with self.assertRaises(PermissionError):
            create_session(c,actor="owner")

    def test_session_csrf_expiry_revoke(self):
        c=sqlite3.connect(":memory:")
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        token,csrf=create_session(c,actor="owner",authenticated=True,now=now)
        self.assertEqual(validate_session(c,token=token,csrf=csrf,require_csrf=True,now=now),"owner")
        with self.assertRaises(PermissionError):
            validate_session(c,token=token,csrf="wrong",require_csrf=True,now=now)
        with self.assertRaises(PermissionError):
            validate_session(c,token=token,now=now+timedelta(minutes=21))
        revoke_session(c,token=token)
        with self.assertRaises(PermissionError):
            validate_session(c,token=token,now=now)

if __name__=="__main__": unittest.main()
