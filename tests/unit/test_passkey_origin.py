import unittest
from gaon.control.passkey_origin import RP_ID,validate_origin

class PasskeyOriginTests(unittest.TestCase):
    def test_exact_https_origin(self):
        for host in (RP_ID,RP_ID+":8443"):
            with self.subTest(host=host):
                self.assertEqual(validate_origin("https://"+host,request_host=host),"https://"+host)

    def test_reject_untrusted_or_cross_origin(self):
        cases=[
            ("http://"+RP_ID,RP_ID),
            ("https://evil.example",RP_ID),
            ("https://"+RP_ID+":8443",RP_ID),
            ("https://"+RP_ID,RP_ID+":8443"),
            ("https://"+RP_ID+".evil.example",RP_ID),
            ("https://"+RP_ID+"/admin",RP_ID),
            ("https://"+RP_ID+"?x=1",RP_ID),
        ]
        for origin,host in cases:
            with self.subTest(origin=origin,host=host):
                with self.assertRaises(PermissionError):
                    validate_origin(origin,request_host=host)

if __name__=="__main__": unittest.main()
