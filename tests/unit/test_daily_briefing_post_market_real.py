import unittest
from unittest import mock

from gaon.runtime import daily_briefing as d


class _Feedback:
    def __init__(self, payload):
        self._payload = payload

    def to_json(self):
        return dict(self._payload)


KR = {"completed_trade_count": 0, "win_rate": None, "failed_order_count": 0, "unconfirmed_order_count": 0,
      "unmatched_sell_count": 0, "open_position_count": 0, "classifications": ["insufficient_live_sample"]}
US = {"completed_trade_count": 11, "win_rate": 0.636, "failed_order_count": 3, "unconfirmed_order_count": 8,
      "unmatched_sell_count": 0, "open_position_count": 2, "classifications": ["execution_failure"]}


class PostMarketUsesRealMarketCodesTests(unittest.TestCase):
    def test_korea_is_queried_as_kr_not_kospi_and_us_block_is_added(self) -> None:
        calls = []

        def fake(market=None):
            calls.append(market)
            return _Feedback({"KR": KR, "US": US}[market])

        with mock.patch("gaon.research.live_trading_intelligence.production_feedback", side_effect=fake):
            text = d._compose_runtime_post_market("2026-11-17T06:40:00Z")
        self.assertEqual(calls, ["KR", "US"])
        self.assertIn("🌆 [국내주식·가온] 장후 브리핑", text)
        self.assertIn("[미국 주식 - 확정 왕복 거래 기준]", text)
        self.assertIn("확정 왕복 거래 11건, 승률 63.6%", text)
        self.assertIn("주문 실패 3건 · 체결 미확인 8건", text)
        self.assertIn("보유 중인 미청산 포지션 2건", text)

    def test_unreadable_orders_are_reported_not_hidden_as_no_issue(self) -> None:
        with mock.patch("gaon.research.live_trading_intelligence.production_feedback", return_value=None):
            text = d._compose_runtime_post_market("2026-11-17T06:40:00Z")
        self.assertIn("주문 기록을 읽지 못해 성과를 계산하지 못했습니다.", text)
        self.assertIn("주문 기록을 읽지 못해 실행 이슈를 확인하지 못했습니다.", text)
        self.assertNotIn("주문 실행 이슈가 확인되지 않았습니다.", text)
        self.assertNotIn("미국 주식", text)

    def test_us_failure_does_not_break_korean_briefing(self) -> None:
        def fake(market=None):
            if market == "US":
                raise RuntimeError("boom")
            return _Feedback(KR)

        with mock.patch("gaon.research.live_trading_intelligence.production_feedback", side_effect=fake):
            text = d._compose_runtime_post_market("2026-11-17T06:40:00Z")
        self.assertIn("확정된 왕복 거래가 없어 성과를 계산하지 않았습니다.", text)
        self.assertNotIn("미국 주식", text)

    def test_market_code_mapping(self) -> None:
        self.assertEqual(d._LIVE_MARKET_CODE["KOSPI"], "KR")
        self.assertEqual(d._LIVE_MARKET_CODE["KOSDAQ"], "KR")


if __name__ == "__main__":
    unittest.main()
