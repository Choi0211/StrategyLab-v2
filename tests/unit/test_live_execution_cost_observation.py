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


if __name__ == "__main__":
    unittest.main()
