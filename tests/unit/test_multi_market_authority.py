import unittest
from datetime import datetime, timezone
from gaon.control.multi_market_authority import may_activate_strategy, may_execute_ai

def approval(market="KR_STOCK", account="A", version="v1"):
    return {"status":"approved","market":market,"account":account,
            "strategy_version_id":version,"approved_by":"human",
            "approval_id":"approval-1","approved_at":datetime.now(timezone.utc).isoformat()}

class MultiMarketAuthorityTests(unittest.TestCase):
    def test_equity_needs_approval(self):
        self.assertFalse(may_activate_strategy(market="KR_STOCK",account="A",strategy_version_id="v1").allowed)

    def test_equity_matching_fields_are_not_sufficient_to_execute(self):
        self.assertTrue(may_activate_strategy(market="KR_STOCK",account="A",strategy_version_id="v1",approval=approval()).allowed)
        self.assertFalse(may_execute_ai(market="KR_STOCK",mode="live",account="A",strategy_version_id="v1",strategy_approval=approval()).allowed)

    def test_wrong_market_account_version(self):
        for kw in ({"market":"US_STOCK"},{"account":"B"},{"strategy_version_id":"v2"}):
            args={"market":"KR_STOCK","account":"A","strategy_version_id":"v1","approval":approval()}
            args.update(kw)
            self.assertFalse(may_activate_strategy(**args).allowed)

    def test_live_binance_locked_even_with_matching_approvals(self):
        a=approval("BINANCE")
        result=may_execute_ai(market="BINANCE",mode="live",account="A",strategy_version_id="v1",strategy_approval=a,live_ai_approval=a)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason,"live_ai_execution_not_validated")

    def test_paper_binance_locked_until_adapter(self):
        self.assertFalse(may_execute_ai(market="BINANCE",mode="paper",account="A",strategy_version_id="v1").allowed)

    def test_invalid_scope(self):
        self.assertFalse(may_execute_ai(market="UNKNOWN",mode="live",account="A",strategy_version_id="v1").allowed)

if __name__=="__main__": unittest.main()
