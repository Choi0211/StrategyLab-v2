import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from gaon.control.passkey_assertion import PendingChallenge
from gaon.control.passkey_challenge_store import store,consume

class PasskeyChallengeStoreTests(unittest.TestCase):
    def test_durable_challenge_scope_and_single_use(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            db=str(Path(tmp_path)/"challenge.sqlite")
            now=datetime(2026,10,18,tzinfo=timezone.utc)
            p=PendingChallenge(b"secret","owner","activate","family","v1",
                               now+timedelta(minutes=2))
            a=sqlite3.connect(db)
            store(a,p)
            a.close()
            b=sqlite3.connect(db)
            args=dict(challenge=b"secret",actor="owner",action="activate",
                      family_id="family",version_id="v1",now=now)
            with self.assertRaisesRegex(PermissionError,"not found"):
                consume(b,**{**args,"version_id":"v2"})
            restored=consume(b,**args)
            self.assertEqual(restored.challenge,p.challenge)
            with self.assertRaisesRegex(PermissionError,"consumed"):
                consume(b,**args)
            b.close()

    def test_expired_challenge_not_consumed(self):
        c=sqlite3.connect(":memory:")
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        store(c,PendingChallenge(b"old","owner","rollback","family","v1",
                                 now-timedelta(seconds=1)))
        with self.assertRaisesRegex(PermissionError,"expired"):
            consume(c,challenge=b"old",actor="owner",action="rollback",
                    family_id="family",version_id="v1",now=now)

if __name__=="__main__": unittest.main()
