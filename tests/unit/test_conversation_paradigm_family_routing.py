"""feature/conversation-paradigm-family-routing (A9).

A user who names a specific strategy PARADIGM in conversation
("평균회귀 전략은 어때?", "모멘텀도 비교해줘", "변동성 전략 연구해봐",
"국면 필터도 봐줘") should have the Research Brain study THAT family next -
distinct from the generic "다른 방식도 찾아봐" (is_diversity_request), which
only asks to rotate. ``requested_strategy_family`` is the deterministic
NLU helper for this; it only CHOOSES a family and never bypasses a
validation or promotion gate.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.research_mission import is_diversity_request, requested_strategy_family
from gaon.knowledge.strategy_candidate import _TEMPLATE_BY_FAMILY


class RequestedStrategyFamilyTests(unittest.TestCase):
    def test_named_paradigms_map_to_their_wired_families(self) -> None:
        cases = {
            "평균회귀 전략은 어때?": "mean_reversion_standard",
            "역추세 매매도 연구해봐": "mean_reversion_standard",
            "모멘텀도 비교해줘": "momentum_roc_standard",
            "momentum 전략 연구해줘": "momentum_roc_standard",
            "변동성 급등 전략은?": "volatility_thrust_standard",
            "volatility 전략도 봐줘": "volatility_thrust_standard",
            "국면 필터 전략 연구해봐": "breakout_regime_filtered",
            "상승 국면에서만 매수하는 전략은?": "breakout_regime_filtered",
        }
        for text, family in cases.items():
            with self.subTest(text=text):
                self.assertEqual(requested_strategy_family(text), family)
                # every mapped family is actually a resolvable template.
                self.assertIn(family, _TEMPLATE_BY_FAMILY)

    def test_generic_or_breakout_or_empty_requests_return_none(self) -> None:
        for text in (
            "",
            "돌파 전략 계속 연구해줘",
            "20일 고가 돌파 전략은?",
            "다른 방식도 찾아봐",
            "연구를 계속해주세요",
            "지금 상황 알려줘",
        ):
            with self.subTest(text=text):
                self.assertIsNone(requested_strategy_family(text))

    def test_named_paradigm_is_not_confused_with_a_diversity_request(self) -> None:
        # "평균회귀 전략은 어때?" is a SPECIFIC ask, not the generic
        # "different approach" ask - the two helpers must not both fire.
        self.assertEqual(requested_strategy_family("평균회귀 전략은 어때?"), "mean_reversion_standard")
        self.assertFalse(is_diversity_request("평균회귀 전략은 어때?"))
        # and vice versa.
        self.assertIsNone(requested_strategy_family("다른 방식도 찾아봐"))
        self.assertTrue(is_diversity_request("다른 방식도 찾아봐"))


if __name__ == "__main__":
    unittest.main()
