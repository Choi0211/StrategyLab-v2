import sqlite3
import unittest
from types import SimpleNamespace
from gaon.control.passkey_repository import (
    enroll_verified,credential_for_actor,accept_verified_assertion)

class PasskeyRepositoryTests(unittest.TestCase):
    def test_passkey_persistence_and_counter_replay(self):
        c=sqlite3.connect(":memory:")
        reg=SimpleNamespace(credential_id=b"id",credential_public_key=b"public",
                            sign_count=1,user_verified=True)
        with self.assertRaises(PermissionError):
            enroll_verified(c,actor="owner",verified=reg)
        enroll_verified(c,actor="owner",verified=reg,trusted_bootstrap=True)
        self.assertEqual(credential_for_actor(c,"owner"),(b"id",b"public",1))
        verified=SimpleNamespace(credential_id=b"id",new_sign_count=2,user_verified=True)
        accept_verified_assertion(c,actor="owner",verified=verified,expected_credential_id=b"id")
        self.assertEqual(credential_for_actor(c,"owner")[2],2)
        with self.assertRaisesRegex(PermissionError,"replay"):
            accept_verified_assertion(c,actor="owner",verified=verified,expected_credential_id=b"id")
        with self.assertRaisesRegex(PermissionError,"mismatch"):
            accept_verified_assertion(c,actor="owner",verified=SimpleNamespace(
                credential_id=b"other",new_sign_count=3,user_verified=True),
                expected_credential_id=b"id")

if __name__=="__main__": unittest.main()
