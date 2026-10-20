"""Unit tests for gaon.research.paper_failure_analysis - deterministic
failure-analysis and hypothesis generation over closed Paper trades.
"""

from __future__ import annotations

import unittest

from gaon.research.paper_failure_analysis import (
    CANDIDATE,
    INSUFFICIENT_EVIDENCE,
    MIN_GROUP_TRADES,
    MIN_TOTAL_TRADES,
    TradeRecord,
    collect_trade_records,
    generate_hypotheses,
)

FAMILY_ID = "csm-48h-long"
NOW = "2026-10-22T00:00:00+00:00"


def _obs(**overrides: object) -> dict:
    base = {
        "family_id": FAMILY_ID, "symbol": "BTCUSDT", "status": "closed",
        "entry_at": "2026-10-20T00:00:00+00:00", "exit_at": "2026-10-22T00:00:00+00:00",
        "entry_price": 100.0, "exit_price": 105.0, "qty": 1.0,
        "pnl": 5.0, "pnl_pct": 0.05, "fees": -0.1, "reason": "48h_timed_exit",
    }
    base.update(overrides)
    return base


class CollectTradeRecordsTests(unittest.TestCase):
    def test_skips_non_closed_statuses(self) -> None:
        obs = [_obs(status="open"), _obs(status="signal_only"), _obs(status="entry_blocked")]
        self.assertEqual(collect_trade_records(obs), [])

    def test_net_pnl_computed_when_both_gross_and_fees_known(self) -> None:
        records = collect_trade_records([_obs(pnl=5.0, fees=-0.5)])
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0].net_pnl, 4.5)
        self.assertEqual(records[0].pnl_basis, "net")
        self.assertTrue(records[0].is_win)

    def test_falls_back_to_gross_pnl_when_fees_unknown_and_flags_the_basis(self) -> None:
        records = collect_trade_records([_obs(pnl=5.0, fees=None)])
        self.assertIsNone(records[0].net_pnl)
        self.assertEqual(records[0].pnl_basis, "gross_fallback")
        self.assertTrue(records[0].is_win)

    def test_no_pnl_known_at_all_leaves_is_win_and_basis_none(self) -> None:
        records = collect_trade_records([_obs(pnl=None, fees=None)])
        self.assertIsNone(records[0].pnl_basis)
        self.assertIsNone(records[0].is_win)

    def test_holding_hours_computed_from_entry_and_exit_timestamps(self) -> None:
        records = collect_trade_records([_obs(
            entry_at="2026-10-20T00:00:00+00:00", exit_at="2026-10-22T00:00:00+00:00",
        )])
        self.assertAlmostEqual(records[0].holding_hours, 48.0)

    def test_holding_hours_is_none_when_a_timestamp_is_missing(self) -> None:
        records = collect_trade_records([_obs(exit_at=None)])
        self.assertIsNone(records[0].holding_hours)

    def test_malformed_numeric_field_does_not_raise(self) -> None:
        records = collect_trade_records([_obs(pnl="not-a-number")])
        self.assertIsNone(records[0].gross_pnl)


def _win(symbol="BTCUSDT", pnl=10.0, fees=-0.1, reason="48h_timed_exit"):
    return _obs(symbol=symbol, pnl=pnl, fees=fees, reason=reason)


def _loss(symbol="BTCUSDT", pnl=-10.0, fees=-0.1, reason="48h_timed_exit"):
    return _obs(symbol=symbol, pnl=pnl, fees=fees, reason=reason)


class GenerateHypothesesTests(unittest.TestCase):
    def test_below_min_total_trades_yields_a_single_insufficient_data_hypothesis(self) -> None:
        records = collect_trade_records([_win()] * (MIN_TOTAL_TRADES - 1))
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        self.assertEqual(len(hyps), 1)
        self.assertEqual(hyps[0].pattern_type, "insufficient_data")
        self.assertEqual(hyps[0].status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(hyps[0].confidence)
        self.assertEqual(hyps[0].trade_count, MIN_TOTAL_TRADES - 1)

    def test_enough_trades_but_no_pattern_fires_yields_no_candidate_for_that_pattern(self) -> None:
        # Perfectly balanced, diversified, cheap trades - nothing should fire.
        obs = []
        symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT"]
        for i in range(MIN_TOTAL_TRADES):
            sign = 1 if i % 2 == 0 else -1
            obs.append(_obs(symbol=symbols[i % len(symbols)], pnl=sign * 10.0, fees=-0.05))
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        pattern_types = {h.pattern_type for h in hyps}
        self.assertNotIn("symbol_concentration", pattern_types)
        self.assertNotIn("fee_drag", pattern_types)

    def test_symbol_concentration_detected_above_threshold(self) -> None:
        obs = [_win(symbol="QNTUSDT", pnl=100.0)]  # dominates
        obs += [_win(symbol=f"SYM{i}USDT", pnl=5.0) for i in range(MIN_TOTAL_TRADES - 1)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        concentration = next(h for h in hyps if h.pattern_type == "symbol_concentration")
        self.assertEqual(concentration.status, CANDIDATE)
        self.assertIn("QNTUSDT", concentration.statement)
        self.assertIsNotNone(concentration.confidence)
        self.assertGreater(concentration.evidence["top_symbol_share"], 0.40)
        self.assertTrue(len(concentration.verification_required) >= 3)

    def test_symbol_concentration_not_flagged_when_broadly_distributed(self) -> None:
        obs = [_win(symbol=f"SYM{i}USDT", pnl=10.0) for i in range(MIN_TOTAL_TRADES)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        self.assertNotIn("symbol_concentration", {h.pattern_type for h in hyps})

    def test_fee_drag_detected_above_threshold(self) -> None:
        obs = [_win(pnl=10.0, fees=-4.0) for _ in range(MIN_TOTAL_TRADES)]  # 40% fee drag
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        drag = next(h for h in hyps if h.pattern_type == "fee_drag")
        self.assertEqual(drag.status, CANDIDATE)
        self.assertAlmostEqual(drag.evidence["fee_to_gross_ratio"], 0.4)

    def test_fee_drag_insufficient_evidence_when_fees_mostly_unknown(self) -> None:
        obs = [_win(pnl=10.0, fees=None) for _ in range(MIN_TOTAL_TRADES)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        drag = next(h for h in hyps if h.pattern_type == "fee_drag")
        self.assertEqual(drag.status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(drag.confidence)

    def test_early_exit_vs_scheduled_gap_detected(self) -> None:
        obs = [_win(reason="48h_timed_exit") for _ in range(MIN_GROUP_TRADES + 2)]
        obs += [_loss(reason="closed_externally") for _ in range(MIN_GROUP_TRADES)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        early = next(h for h in hyps if h.pattern_type == "early_exit_vs_scheduled")
        self.assertEqual(early.status, CANDIDATE)
        self.assertAlmostEqual(early.evidence["scheduled_exit_win_rate"], 1.0)
        self.assertAlmostEqual(early.evidence["early_exit_win_rate"], 0.0)

    def test_stop_loss_and_take_profit_reasons_are_both_counted_as_early_exit(self) -> None:
        obs = [_win(reason="48h_timed_exit") for _ in range(MIN_GROUP_TRADES + 2)]
        obs += [_loss(reason="stop_loss") for _ in range(MIN_GROUP_TRADES - 2)]
        obs += [_loss(reason="take_profit") for _ in range(2)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        early = next(h for h in hyps if h.pattern_type == "early_exit_vs_scheduled")
        self.assertEqual(early.evidence["early_exit_trade_count"], MIN_GROUP_TRADES)
        self.assertEqual(early.evidence["early_exit_reason_counts"]["stop_loss"], MIN_GROUP_TRADES - 2)
        self.assertEqual(early.evidence["early_exit_reason_counts"]["take_profit"], 2)
        self.assertEqual(early.evidence["early_exit_reason_counts"]["closed_externally"], 0)

    def test_early_exit_insufficient_evidence_when_one_group_too_small(self) -> None:
        obs = [_win(reason="48h_timed_exit") for _ in range(MIN_GROUP_TRADES + 5)]
        obs += [_loss(reason="closed_externally") for _ in range(MIN_GROUP_TRADES - 1)]
        records = collect_trade_records(obs)
        hyps = generate_hypotheses(FAMILY_ID, records, now=NOW)
        early = next(h for h in hyps if h.pattern_type == "early_exit_vs_scheduled")
        self.assertEqual(early.status, INSUFFICIENT_EVIDENCE)

    def test_fingerprint_is_deterministic_for_identical_evidence(self) -> None:
        obs = [_win(symbol="QNTUSDT", pnl=100.0)]
        obs += [_win(symbol=f"SYM{i}USDT", pnl=5.0) for i in range(MIN_TOTAL_TRADES - 1)]
        records = collect_trade_records(obs)
        hyps1 = generate_hypotheses(FAMILY_ID, records, now=NOW)
        hyps2 = generate_hypotheses(FAMILY_ID, records, now="2099-01-01T00:00:00+00:00")  # different `now`
        fp1 = {h.pattern_type: h.fingerprint for h in hyps1}
        fp2 = {h.pattern_type: h.fingerprint for h in hyps2}
        self.assertEqual(fp1, fp2)  # fingerprint must not depend on `now`

    def test_hypothesis_to_dict_round_trips_expected_keys(self) -> None:
        records = collect_trade_records([_win()] * (MIN_TOTAL_TRADES - 1))
        hyp = generate_hypotheses(FAMILY_ID, records, now=NOW)[0]
        d = hyp.to_dict()
        for key in ("family_id", "pattern_type", "hypothesis_id", "fingerprint", "status",
                    "statement", "trade_count", "confidence", "evidence",
                    "expected_improvement", "verification_required", "generated_at"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
