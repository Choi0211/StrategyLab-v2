from __future__ import annotations
from datetime import date,timedelta
import os,unittest
from gaon.research.multi_symbol import AutonomousMultiSymbolResearchOrchestrator
from gaon.research.real_research import DataQualityEngine,MarketBar,MarketDataMetadata,MarketDataset,MarketSymbol

US_WHOLE_MARKET_REQUEST = ("\ubbf8\uad6d \uc8fc\uc2dd \uc804\uccb4\ub97c \uc5f0\uad6c\ud574\uc918")
class C:
    def __init__(self,d): self.d=tuple(d)
    def expected_open_dates(self,*,start_date,end_date): return tuple(x for x in self.d if start_date<=x<=end_date)
class P:
    source="real:unit-global"; market_agnostic=True
    def __init__(self): self.refs={"AAPL":MarketSymbol("AAPL","Apple","US","NASDAQ"),"MSFT":MarketSymbol("MSFT","MS","US","NASDAQ"),"IBM":MarketSymbol("IBM","IBM","US","NYSE"),"BMY":MarketSymbol("BMY","BMY","US","NYSE"),"ABC":MarketSymbol("ABC","ABC","US","AMEX")}
    def fetch_universe(self,s): return tuple(self.refs.values())
    def fetch_bars(self,symbol,*,start_date,end_date,timeframe="daily"):
        r=self.refs[symbol]; bars=[]; d=date.fromisoformat(start_date); last=date.fromisoformat(end_date); i=0
        while d<=last:
            if d.weekday()<5:
                c=100+i*.5+(3 if i%19==0 else 0); v=1000000+i*1000; bars.append(MarketBar(d.isoformat(),symbol,c-.5,c+1,c-1,c,v,int(v*c))); i+=1
            d+=timedelta(days=1)
        m=MarketDataMetadata(self.source,r.exchange,"daily",bars[0].timestamp,bars[-1].timestamp,True,"2026-08-16T00:00:00Z",False); return MarketDataset(f"dataset:unit:{symbol}:{bars[0].timestamp}:{bars[-1].timestamp}",(r,),tuple(bars),m)
    def validate_dataset(self,d): return DataQualityEngine().validate(d,min_bars=60,calendar=C(tuple(x.timestamp for x in d.bars)))
class GlobalMultiSymbolResearchTests(unittest.TestCase):
    def test_us_market_snapshot(self):
        run=AutonomousMultiSymbolResearchOrchestrator(None,P()).run(US_WHOLE_MARKET_REQUEST,symbols=(),universe_type="curated",start_date="2025-01-02",end_date="2026-01-30",generated_at="2026-08-16T00:00:00Z"); u=run.request.universe; self.assertEqual("US",u.market); self.assertEqual(5,u.candidate_count); self.assertEqual(5,len(u.symbols)); self.assertEqual("exhaustive",u.coverage_mode); self.assertFalse(run.request.fixture_backed); self.assertIn("market=US",run.korean_report)
    def test_budget_not_exhaustive(self):
        old=os.environ.get("GAON_GLOBAL_RESEARCH_MAX_SYMBOLS"); os.environ["GAON_GLOBAL_RESEARCH_MAX_SYMBOLS"]="3"
        try: run=AutonomousMultiSymbolResearchOrchestrator(None,P()).run(US_WHOLE_MARKET_REQUEST,symbols=(),universe_type="curated",start_date="2025-01-02",end_date="2026-01-30",generated_at="2026-08-16T00:00:00Z")
        finally:
            if old is None: os.environ.pop("GAON_GLOBAL_RESEARCH_MAX_SYMBOLS",None)
            else: os.environ["GAON_GLOBAL_RESEARCH_MAX_SYMBOLS"]=old
        u=run.request.universe; self.assertEqual(5,u.candidate_count); self.assertEqual(3,len(u.symbols)); self.assertEqual("bounded_cross_exchange_sample",u.coverage_mode); self.assertFalse(u.to_json()["exhaustive"])


def test_kr_us_compare_routes_to_multi_symbol():
    from gaon.runtime.llm_tool_routing import route_read_only_tool

    text = (
        "\uac00\uc628\uc544 \ud55c\uad6d\uacfc \ubbf8\uad6d "
        "\uc8fc\uc2dd \uc804\uccb4\ub97c \ub300\uc0c1\uc73c\ub85c "
        "\ube44\uad50 \uc5f0\uad6c\ud574\uc918. "
        "\ucf54\uc2a4\ud53c, \ucf54\uc2a4\ub2e5, "
        "\ub098\uc2a4\ub2e5, NYSE, AMEX\ub97c "
        "\ud3ec\ud568\ud574\uc918."
    )

    assert (
        route_read_only_tool(text)
        == "multi_symbol_research"
    )
