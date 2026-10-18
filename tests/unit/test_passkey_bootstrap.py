import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from gaon.control.passkey_bootstrap import create_local_grant,consume_local_grant

class PasskeyBootstrapTests(unittest.TestCase):
    def test_local_grant_is_one_time_and_actor_scoped(self):
        c=sqlite3.connect(":memory:")
        token=create_local_grant(c,actor="owner")
        self.assertNotIn(token,str(c.execute("SELECT * FROM gaon_passkey_bootstrap").fetchall()))
        with self.assertRaises(PermissionError):
            consume_local_grant(c,actor="other",token=token)
        self.assertTrue(consume_local_grant(c,actor="owner",token=token))
        with self.assertRaises(PermissionError):
            consume_local_grant(c,actor="owner",token=token)

    def test_expired_grant_is_rejected(self):
        c=sqlite3.connect(":memory:")
        now=datetime.now(timezone.utc)
        token=create_local_grant(c,actor="owner",now=now)
        with self.assertRaises(PermissionError):
            consume_local_grant(c,actor="owner",token=token,
                now=now+timedelta(minutes=11))

if __name__=="__main__": unittest.main()
