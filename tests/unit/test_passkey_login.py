import sqlite3
import unittest
from gaon.control.passkey_login import begin_login,finish_login
from gaon.control.passkey_origin import RP_ID

class PasskeyLoginTests(unittest.TestCase):
    def test_unknown_actor_cannot_begin(self):
        with self.assertRaises(PermissionError):
            begin_login(sqlite3.connect(":memory:"),actor="unknown",
                origin="https://"+RP_ID,request_host=RP_ID)

    def test_finish_without_credential_rejected(self):
        with self.assertRaises(PermissionError):
            finish_login(sqlite3.connect(":memory:"),actor="owner",credential={},
                origin="https://"+RP_ID,request_host=RP_ID)

    def test_wrong_origin_rejected(self):
        with self.assertRaises(PermissionError):
            begin_login(sqlite3.connect(":memory:"),actor="owner",
                origin="https://evil.example",request_host=RP_ID)

if __name__=="__main__": unittest.main()
