import unittest
from gaon.runtime.web_api import GaonWebChatAdapter,dispatch_request
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.control.passkey_origin import RP_ID

class PasskeyStatusRouteTests(unittest.TestCase):
    def test_readonly_passkey_status_route(self):
        store=RuntimeStateStore(":memory:")
        try:
            adapter=GaonWebChatAdapter(GaonRuntimeConfig(assistant_enabled=False),
                                       store._connection)
            code,payload=dispatch_request(adapter,method="GET",
                path="/gaon/admin/passkey/status",body=None)
            self.assertEqual(code,200)
            self.assertEqual(payload["passkey_rp_id"],RP_ID)
            self.assertIs(payload["registration_complete"],False)
            self.assertIs(payload["strategy_approval_enabled"],False)
            self.assertIs(payload["order_executed"],False)
            code,_=dispatch_request(adapter,method="POST",
                path="/gaon/strategy/version/activate",
                body={"confirm":True})
            self.assertEqual(code,403)
        finally:
            store.close()

if __name__=="__main__": unittest.main()
