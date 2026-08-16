from __future__ import annotations
import unittest
from gaon.runtime.llm_conversation import _default_tool_arguments,_extract_krx_market_scope,_autonomous_learning_request_mode
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.research.multi_symbol import _requested_krx_market_scope
class KRXWholeMarketConversationRoutingTests(unittest.TestCase):
    def test_whole_market(self):
        t="\ud55c\uad6d \uc8fc\uc2dd \uc804\uccb4\ub97c \ub300\uc0c1\uc73c\ub85c \uc5f0\uad6c\ud574\uc8fc\uc138\uc694"
        self.assertEqual("multi_symbol_research",route_read_only_tool(t)); self.assertIsNone(_autonomous_learning_request_mode(t))
        a=_default_tool_arguments("multi_symbol_research",t); self.assertEqual((),a["symbols"]); self.assertEqual("curated",a["universe_type"])
    def test_scope_refinement(self):
        t="\ucf54\uc2a4\ud53c \ucf54\uc2a4\ub2e5\uc744 \uae30\uc900\uc73c\ub85c \ud574\uc8fc\uc138\uc694"
        self.assertEqual("multi_symbol_research",route_read_only_tool(t)); self.assertEqual("ALL",_extract_krx_market_scope(t)); self.assertEqual("ALL",_requested_krx_market_scope(t))
if __name__=="__main__": unittest.main()
