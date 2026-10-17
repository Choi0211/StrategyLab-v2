from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gaon.research.live_trading_intelligence import _binance_feedback


class BinanceExecutionCostObservationTests(unittest.TestCase):
    def test_fill_commission_rate_is_observed_without_fabricating_slippage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {
                    "symbol": f"T{i}USDT",
                    "realized_pnl_usdt": 1.0 if i % 2 == 0 else -0.5,
                    "closed_at": f"2026-10-17T00:{i:02d}:00Z",
                }
                for i in range(20)
            ]
            (root / "trade_events.json").write_text(json.dumps(events), encoding="utf-8")
            verification = {
                "paper_results": [
                    {
                        "checks": {
                            "entry_fill_trace": {
                                "detail": {"total_qty": 10, "avg_price": 10, "total_commission": 0.05, "partial_fill_detected": False}
                            },
                            "exit_fill_trace": {
                                "detail": {"total_qty": 10, "avg_price": 10, "total_commission": 0.05, "partial_fill_detected": True}
                            },
                        }
                    }
                ],
                "live_results": [],
            }
            (root / "trade_capture_verification_log.jsonl").write_text(json.dumps(verification) + "\n", encoding="utf-8")

            feedback = _binance_feedback(root)

            self.assertIsNotNone(feedback)
            assert feedback is not None
            self.assertEqual(feedback.commission_observation_count, 2)
            self.assertAlmostEqual(feedback.observed_commission_rate or 0.0, 0.0005, places=10)
            self.assertEqual(feedback.slippage_observation_count, 0)
            self.assertEqual(feedback.partial_fill_count, 1)
            payload = feedback.to_json()
            self.assertEqual(payload["cost_model_observation_status"], "commission_observed_slippage_missing")
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])

    def test_strategy_identity_is_read_only_from_append_only_archives_without_guessing_unknown_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rolling = [
                {"symbol": f"T{i}USDT", "realized_pnl_usdt": 0.1, "closed_at": f"2026-10-17T00:{i:02d}:00Z"}
                for i in range(20)
            ]
            (root / "trade_events.json").write_text(json.dumps(rolling), encoding="utf-8")
            paper_rows = [
                {"event_id":"e1","symbol":"AAAUSDT","strategy_id":"flow_rsi30","ownership_provenance":"BOT_MANAGED","side":"LONG","realized_pnl_usdt":1.0,"net_pnl_usdt":0.9,"fee_usdt":-0.1,"closed_at":"2026-10-17T01:00:00Z"},
                {"event_id":"e2","symbol":"BBBUSDT","strategy_id":"flow_rsi30","ownership_provenance":"BOT_MANAGED","side":"SHORT","realized_pnl_usdt":-0.5,"net_pnl_usdt":-0.6,"fee_usdt":-0.1,"closed_at":"2026-10-17T02:00:00Z"},
                # duplicate event_id must never double count
                {"event_id":"e2","symbol":"BBBUSDT","strategy_id":"flow_rsi30","ownership_provenance":"BOT_MANAGED","side":"SHORT","realized_pnl_usdt":-0.5,"closed_at":"2026-10-17T02:00:00Z"},
                # old archive row: no strategy identity, remains unclassified
                {"event_id":"e3","symbol":"CCCUSDT","realized_pnl_usdt":2.0,"closed_at":"2026-10-17T03:00:00Z"},
                # explicit non-bot provenance cannot become bot strategy evidence
                {"event_id":"e4","symbol":"DDDUSDT","strategy_id":"flow_rsi30","ownership_provenance":"MANUAL_EXTERNAL","realized_pnl_usdt":3.0,"closed_at":"2026-10-17T04:00:00Z"},
            ]
            live_rows = [
                {"event_id":"e5","symbol":"EEEUSDT","strategy_id":"flow_rsi30","ownership_provenance":"BOT_MANAGED","side":"LONG","realized_pnl_usdt":0.2,"closed_at":"2026-10-17T05:00:00Z"},
            ]
            (root / "trade_events.json.archive.jsonl").write_text("\n".join(json.dumps(x) for x in paper_rows)+"\n", encoding="utf-8")
            (root / "live_trade_events.json.archive.jsonl").write_text("\n".join(json.dumps(x) for x in live_rows)+"\n", encoding="utf-8")

            feedback = _binance_feedback(root)

            self.assertIsNotNone(feedback)
            assert feedback is not None
            self.assertEqual(feedback.strategy_identity_total_count, 5)
            self.assertEqual(feedback.strategy_identity_observation_count, 3)
            self.assertAlmostEqual(feedback.to_json()["strategy_identity_coverage"], 0.6)
            by_mode = {(x["mode"], x["strategy_id"]): x for x in feedback.strategy_performance}
            self.assertEqual(set(by_mode), {("paper", "flow_rsi30"), ("live", "flow_rsi30")})
            paper = by_mode[("paper", "flow_rsi30")]
            self.assertEqual(paper["completed_trade_count"], 2)
            self.assertEqual(paper["win_count"], 1)
            self.assertAlmostEqual(paper["total_realized_pnl"], 0.5)
            self.assertEqual(paper["net_pnl_observation_count"], 2)
            self.assertAlmostEqual(paper["observed_net_pnl_total"], 0.3)
            self.assertEqual(paper["long_trade_count"], 1)
            self.assertEqual(paper["short_trade_count"], 1)
            self.assertNotIn("unknown", {x["strategy_id"] for x in feedback.strategy_performance})
            self.assertFalse(feedback.to_json()["strategy_mutated"])
            self.assertFalse(feedback.to_json()["order_executed"])


if __name__ == "__main__":
    unittest.main()
