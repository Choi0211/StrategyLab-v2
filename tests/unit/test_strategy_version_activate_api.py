import unittest
from gaon.control.strategy_version import StrategyVersionRegistry
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository
from gaon.runtime.web_api import GaonWebChatAdapter, dispatch_request

F='binance-price-action'; T='2026-09-26T07:00:00Z'
class ActivateApiTests(unittest.TestCase):
 def setUp(self):
  self.store=RuntimeStateStore(':memory:'); self.addCleanup(self.store.close)
  self.a=GaonWebChatAdapter(GaonRuntimeConfig(assistant_enabled=False),self.store._connection)
  r=StrategyVersionRegistry(); self.l=r.register_apply_ready(family_id=F,candidate_id='l',spec_fingerprint='lfp',spec_rules={'entry':{}},validation_summary={},at=T,direction='LONG'); self.s=r.register_apply_ready(family_id=F,candidate_id='s',spec_fingerprint='sfp',spec_rules={'entry':{}},validation_summary={},at=T,direction='SHORT'); StrategyVersionSQLiteRepository(self.store._connection).save(F,r,now=T)
 def post(self,vid,confirm=True): return dispatch_request(self.a,method='POST',path='/gaon/strategy/version/activate',body={'family_id':F,'strategy_version_id':vid,'confirm':confirm})
 def test_confirmation_required_and_no_mutation(self):
  code,p=self.post(self.l.strategy_version_id,False); self.assertEqual(code,409); self.assertFalse(p['strategy_mutated']); self.assertIsNone(self.a.strategy_version_status(F)['active_by_direction']['LONG'])
 def test_long_and_short_activate_independently(self):
  code,p=self.post(self.l.strategy_version_id); self.assertEqual(code,200); self.assertTrue(p['strategy_mutated']); self.assertFalse(p['order_executed']); self.assertIsNotNone(p['active_by_direction']['LONG']); self.assertIsNone(p['active_by_direction']['SHORT'])
  code,p=self.post(self.s.strategy_version_id); self.assertEqual(code,200); self.assertEqual(p['active_by_direction']['LONG']['spec_fingerprint'],'lfp'); self.assertEqual(p['active_by_direction']['SHORT']['spec_fingerprint'],'sfp')
 def test_unknown_fails_closed(self):
  code,p=self.post('missing'); self.assertEqual(code,409); self.assertFalse(p['strategy_mutated']); self.assertFalse(p['order_executed'])
if __name__=='__main__': unittest.main()
