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
 def test_direct_adapter_confirmation_is_also_denied(self):
  for version in (self.l.strategy_version_id,self.s.strategy_version_id):
   result=self.a.activate_strategy_version(family_id=F,strategy_version_id=version,confirm=True,now=T)
   self.assertFalse(result['ok'])
   self.assertFalse(result['strategy_mutated'])
  state=self.a.strategy_version_status(F)['active_by_direction']
  self.assertIsNone(state['LONG'])
  self.assertIsNone(state['SHORT'])
 def test_confirmation_does_not_authorize_mutation(self):
  for version in (self.l.strategy_version_id,self.s.strategy_version_id,'missing'):
   for confirm in (True,False):
    code,p=self.post(version,confirm)
    self.assertEqual(code,403)
    self.assertFalse(p['strategy_mutated'])
    self.assertFalse(p['order_executed'])
    self.assertFalse(p['approval_bypassed'])
  state=self.a.strategy_version_status(F)['active_by_direction']
  self.assertIsNone(state['LONG'])
  self.assertIsNone(state['SHORT'])
if __name__=='__main__': unittest.main()
