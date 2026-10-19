import unittest
from datetime import datetime,timezone,timedelta
from gaon.control.passkey_assertion import begin_assertion,finish_assertion

class PasskeyAssertionTests(unittest.TestCase):
    def test_scoped_challenge_and_replay_block(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        options,p=begin_assertion(rp_id="example.com",credential_id=b"abc",
            actor="owner",action="activate",family_id="test",version_id="v1",now=now)
        self.assertIn("challenge",options)
        kw=dict(pending=p,credential={},credential_public_key=b"bad",sign_count=0,
            rp_id="example.com",origin="https://example.com",actor="owner",
            action="activate",family_id="test",version_id="v1",now=now)
        with self.assertRaisesRegex(PermissionError,"scope"):
            finish_assertion(**{**kw,"version_id":"v2"})
        self.assertFalse(p.consumed)
        with self.assertRaises(Exception):
            finish_assertion(**kw)
        self.assertTrue(p.consumed)
        with self.assertRaisesRegex(PermissionError,"consumed"):
            finish_assertion(**kw)

    def test_expiry(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        _,p=begin_assertion(rp_id="example.com",credential_id=b"abc",
            actor="owner",action="rollback",family_id="test",version_id="v1",now=now)
        with self.assertRaisesRegex(PermissionError,"expired"):
            finish_assertion(pending=p,credential={},credential_public_key=b"x",
                sign_count=0,rp_id="example.com",origin="https://example.com",
                actor="owner",action="rollback",family_id="test",version_id="v1",
                now=now+timedelta(minutes=3))

if __name__=="__main__": unittest.main()
