import unittest
from unittest import mock

from gaon.runtime import daily_briefing as d


class _Fb:
    def to_json(self):
        return {"completed_trade_count": 0, "win_rate": None, "failed_order_count": 0,
                "unconfirmed_order_count": 0, "unmatched_sell_count": 0, "open_position_count": 0,
                "classifications": []}


class MergedReviewTests(unittest.TestCase):
    def test_post_market_contains_unresolved_review_section(self) -> None:
        review = {"unresolved_count": 1, "unresolved": [{"symbol": "005930", "action": "extend_validation_window", "reason": ""}]}
        with mock.patch("gaon.research.live_trading_intelligence.production_feedback", return_value=_Fb()), \
             mock.patch.object(d, "compose_unresolved_research_review", return_value=review):
            text = d._compose_runtime_post_market("2026-11-17T06:40:00Z", audit_records_provider=lambda: ())
        self.assertIn("[미해결 연구 점검]", text)
        self.assertIn("005930", text)
        self.assertEqual(text.count("[연구 미션]"), 0)

    def test_unreadable_audit_is_reported(self) -> None:
        def boom():
            raise RuntimeError("x")
        with mock.patch("gaon.research.live_trading_intelligence.production_feedback", return_value=_Fb()):
            text = d._compose_runtime_post_market("2026-11-17T06:40:00Z", audit_records_provider=boom)
        self.assertIn("연구 기록을 읽지 못해", text)


if __name__ == "__main__":
    unittest.main()
