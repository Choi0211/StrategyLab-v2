"""Unit checks; synthetic *test fixtures*, never confused with real research."""
import unittest
import kospi_reversal_research as s

class ReversalOrderContract(unittest.TestCase):
    def setUp(self):
        self.idx=[(f'2026-10-{day:02d}',1000.) for day in range(1,16)]
        self.signal=[{'signal_date':'2026-10-01','code':'005930','name':'fixture',
                      'close':100,'return5':-0.10,'prior_closes':[105,104,103,102,100]}]
        self.bar={'o':102,'h':103,'l':98,'c':102,'v':100,'shares':1_000_000}
        self.nextbar={'o':105,'h':106,'l':104,'c':105,'v':100,'shares':1_000_000}
    def test_no_same_day_trade_and_limit_is_respected(self):
        bar=self.bar.copy()
        bars={('2026-10-02','005930'):bar,('2026-10-03','005930'):self.nextbar,('2026-10-04','005930'):{'o':105,'h':106,'l':104,'c':105,'v':100,'shares':1_000_000}}
        a=s.run_variant('A_limit',self.signal,self.idx,bars)
        self.assertEqual(a['filled'],1)
        self.assertEqual(a['events'][0]['entry_date'],'2026-10-02')
        self.assertEqual(a['events'][0]['exit_date'],'2026-10-04')
        self.assertLessEqual(a['events'][0]['entry_price'],99.0)
    def test_price_touch_not_guaranteed_in_conservative(self):
        just_touch=self.bar.copy();just_touch['l']=99.0
        bars={('2026-10-02','005930'):just_touch,('2026-10-03','005930'):self.nextbar,('2026-10-04','005930'):{'o':105,'h':106,'l':104,'c':105,'v':100,'shares':1_000_000}}
        a=s.run_variant('A_limit',self.signal,self.idx,bars)
        c=s.run_variant('C_conservative_limit',self.signal,self.idx,bars)
        self.assertEqual(a['filled'],1)
        self.assertEqual(c['filled'],0)
    def test_conservative_entry_does_not_exceed_limit(self):
        bars={('2026-10-02','005930'):self.bar,('2026-10-03','005930'):self.nextbar,('2026-10-04','005930'):{'o':105,'h':106,'l':104,'c':105,'v':100,'shares':1_000_000}}
        c=s.run_variant('C_conservative_limit',self.signal,self.idx,bars)
        self.assertEqual(c['filled'],1)
        self.assertLessEqual(c['events'][0]['entry_price'],99.)
    def test_no_signal_no_orders(self):
        b=s.run_variant('B_next_open',[],self.idx,{})
        self.assertEqual(b['filled'],0);self.assertEqual(len(b['events']),0)
    def test_year_specific_tax(self):
        prev=s.TAX_POLICY
        try:
            s.TAX_POLICY='historical'
            self.assertEqual(s.sale_tax('2019-01-03'),.003)
            self.assertEqual(s.sale_tax('2020-01-03'),.0025)
            self.assertEqual(s.sale_tax('2021-03-03'),.0023)
            self.assertEqual(s.sale_tax('2024-03-03'),.0018)
            self.assertEqual(s.sale_tax('2025-03-03'),.0015)
            self.assertEqual(s.sale_tax('2026-03-03'),.002)
        finally:s.TAX_POLICY=prev
if __name__=='__main__':unittest.main()
