from __future__ import annotations
import unittest
from gaon.knowledge.autonomous_quant_partner import _dynamic_hypothesis_candidate,_evolved_hypothesis_drivers,_select_unique_evolved_hypothesis_candidate,_strategy_semantic_fingerprint
from gaon.research.krx_real_pipeline import CanonicalStrategySpec,FieldProvenance,ProvenancedValue
def _v(x): return ProvenancedValue(x,FieldProvenance.DEFAULT)
def _b(): return CanonicalStrategySpec("s","005930",{"breakout_lookback":_v(30),"close_gt_ma20":_v(True)},{"protective_stop_pct":_v(-5.0)},{"volume_gte_ma20":_v(True)},"t","2026-08-16T00:00:00Z")
class AutonomousResearchConvergenceTests(unittest.TestCase):
    def test_evidence_and_cross_family(self):
        base={"family":"dynamic_fold_consistency_rebalance","mechanism":"m","pass_ratio":0.0}
        drivers=_evolved_hypothesis_drivers("walk_forward_fail",base,research={"provider_states":{"official_market":"success","corporate":"success"}})
        self.assertGreaterEqual(len(drivers),3); self.assertIn("official_market",drivers[1]["evidence_categories"])
        b=_b(); known=set()
        for v in range(3):
            c,_,_=_dynamic_hypothesis_candidate(b,observed_failure="walk_forward_fail",iteration=1,variant=v,driver=drivers[0])
            known.add(_strategy_semantic_fingerprint(c))
        c,changes,sem,skipped,fam,driver=_select_unique_evolved_hypothesis_candidate(b,observed_failure="walk_forward_fail",iteration=1,known_semantic_fingerprints=known,base_driver=base,research={"provider_states":{"official_market":"success"}},max_variants=3)
        self.assertIsNotNone(c); self.assertNotIn(sem,known); self.assertGreater(driver["evolution_stage"],0); self.assertNotEqual(base["family"],fam); self.assertTrue(changes)
if __name__=="__main__": unittest.main()
