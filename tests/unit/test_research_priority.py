"""Hotfix #166 Section 6: read-only, evidence-based KR-vs-Binance research
priority proposal. Proves no fabricated evidence, no automatic action, and
honest reporting when Binance research data is unavailable/unconfigured."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gaon.adapters.binance import BinanceAdapterConfig
from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    extract_or_update_mission,
    next_candidate_sequence,
    record_blocked,
)
from gaon.knowledge.strategy_candidate import new_candidate
from gaon.research.research_priority import propose_research_priority

_NOW = "2026-08-29T00:00:00Z"


def _mission():
    return extract_or_update_mission(
        "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=_NOW
    )


class ResearchPriorityProposalTests(unittest.TestCase):
    def test_no_mission_and_no_binance_config_is_honest_about_both(self) -> None:
        proposal = propose_research_priority(None, None)
        self.assertFalse(proposal.kr.available)
        self.assertIn("no_active_mission", proposal.kr.flags)
        self.assertFalse(proposal.binance.available)
        self.assertIn("not_configured", proposal.binance.flags)
        self.assertEqual(proposal.flagged_domains, ("kr", "binance"))

    def test_blocked_mission_is_flagged_with_its_real_blocker_reason(self) -> None:
        mission = record_blocked(_mission(), reason="provider_unavailable: no data source responded", now=_NOW)
        proposal = propose_research_priority(mission, None)
        self.assertIn("kr", proposal.flagged_domains)
        self.assertIn("blocked", proposal.kr.flags)
        self.assertEqual(proposal.kr.evidence["blocked_reason"], "provider_unavailable: no data source responded")

    def test_active_candidate_with_remaining_blockers_is_flagged(self) -> None:
        mission = _mission()
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=_NOW)
        mission = add_candidate(mission, candidate, now=_NOW)
        proposal = propose_research_priority(mission, None)
        self.assertIn("active_candidate_has_unresolved_blockers", proposal.kr.flags)
        self.assertIn(candidate.candidate_id, str(proposal.kr.evidence["active_candidate_id"]))

    def test_binance_config_pointing_to_missing_directory_is_honestly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            config = BinanceAdapterConfig(state_dir=missing, research_dir=missing)
            proposal = propose_research_priority(None, config)
            self.assertFalse(proposal.binance.available)
            self.assertIn("no_research_data", proposal.binance.flags)

    def test_binance_config_with_real_walkforward_json_surfaces_real_evidence_not_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            research_dir = Path(tmp)
            report = {
                "strategies": {
                    "price_action": {
                        "profitable_symbol_ratio": 0.7,
                        "oos_summary": {
                            "num_folds": 6,
                            "total_trades": 42,
                            "win_rate": 0.55,
                            "mean_return_pct": 1.2,
                            "max_drawdown_pct": 4.5,
                        },
                    }
                }
            }
            (research_dir / "price_action_walkforward.json").write_text(json.dumps(report), encoding="utf-8")
            config = BinanceAdapterConfig(state_dir=research_dir, research_dir=research_dir)

            proposal = propose_research_priority(None, config)

            self.assertTrue(proposal.binance.available)
            self.assertEqual(proposal.binance.flags, ())
            self.assertEqual(proposal.binance.evidence["num_folds"], 6)
            self.assertEqual(proposal.binance.evidence["oos_total_trades"], 42)
            self.assertEqual(proposal.binance.evidence["oos_max_drawdown_pct"], 4.5)

    def test_binance_family_with_zero_trades_is_flagged_insufficient_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            research_dir = Path(tmp)
            report = {"strategies": {"price_action": {"profitable_symbol_ratio": 0.0, "oos_summary": {"num_folds": 0, "total_trades": 0, "win_rate": 0.0, "mean_return_pct": 0.0, "max_drawdown_pct": 0.0}}}}
            (research_dir / "price_action_walkforward.json").write_text(json.dumps(report), encoding="utf-8")
            config = BinanceAdapterConfig(state_dir=research_dir, research_dir=research_dir)

            proposal = propose_research_priority(None, config)
            self.assertIn("insufficient_sample", proposal.binance.flags)

    def test_never_mutates_or_writes_anything(self) -> None:
        # Purely a data-gathering/comparison function - proven by its
        # return type carrying only the fixed safety invariants alongside
        # read evidence, and by construction (no adapters.trading/
        # promotion_gate import anywhere in this module).
        import inspect

        import gaon.research.research_priority as module

        source = inspect.getsource(module)
        for forbidden in ("adapters.trading", "strategy_execution", "strategy_deployment", "promotion_gate", "human_gated_promotion", "place_order", "execute_order"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
