import unittest
from datetime import datetime,timezone,timedelta
from gaon.control.passkey_enrollment import begin_enrollment,finish_enrollment

class PasskeyEnrollmentTests(unittest.TestCase):
    def test_enrollment_needs_trusted_bootstrap(self):
        with self.assertRaises(PermissionError):
            begin_enrollment(rp_id="example.com",actor="owner")

    def test_enrollment_scoped_and_one_time(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        options,p=begin_enrollment(rp_id="example.com",actor="owner",
            bootstrap_authorized=True,now=now)
        self.assertIn('"challenge"',options)
        kw=dict(pending=p,credential={},rp_id="example.com",
            origin="https://example.com",actor="owner",now=now)
        with self.assertRaisesRegex(PermissionError,"actor"):
            finish_enrollment(**{**kw,"actor":"intruder"})
        self.assertFalse(p.consumed)
        with self.assertRaises(Exception):
            finish_enrollment(**kw)
        self.assertTrue(p.consumed)
        with self.assertRaisesRegex(PermissionError,"consumed"):
            finish_enrollment(**kw)

    def test_enrollment_expires(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        _,p=begin_enrollment(rp_id="example.com",actor="owner",
            bootstrap_authorized=True,now=now)
        with self.assertRaisesRegex(PermissionError,"expired"):
            finish_enrollment(pending=p,credential={},rp_id="example.com",
                origin="https://example.com",actor="owner",now=now+timedelta(minutes=3))

if __name__=="__main__": unittest.main()
