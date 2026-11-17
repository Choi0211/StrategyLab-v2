import unittest

from gaon.runtime import daily_briefing as d


class BriefingKoreanWordingTests(unittest.TestCase):
    def test_actions_and_blockers_are_translated_but_unknown_terms_pass_through(self) -> None:
        self.assertEqual(d._ko_term("RUN_OOS", d._ACTION_KO), "표본 외 검증 실행")
        self.assertEqual(d._ko_term("out_of_sample_blocker", d._BLOCKER_KO), "표본 외 검증 미통과")
        self.assertEqual(d._ko_term("minimum_trade_sample", d._BLOCKER_KO), "최소 거래 표본")
        self.assertEqual(d._ko_term("some_new_blocker", d._BLOCKER_KO), "some_new_blocker")

    def test_market_label_and_time_fallback(self) -> None:
        self.assertEqual(d._market_label_ko("KOSPI"), "국내주식")
        self.assertEqual(d._market_label_ko("NASDAQ"), "NASDAQ")
        self.assertEqual(d._kst_or_raw("2026-11-17T07:10:04Z"), "2026-11-17 16:10 KST")
        self.assertEqual(d._kst_or_raw("not-a-time"), "not-a-time")

    def test_unresolved_review_header_uses_unified_pattern_and_kst(self) -> None:
        text = d.render_unresolved_research_review_ko(
            {"unresolved_count": 0, "unresolved": []}, generated_at="2026-11-17T07:10:04Z"
        )
        self.assertEqual(text.splitlines()[0], "🔎 [국내주식·가온] 미해결 연구 점검")
        self.assertEqual(text.splitlines()[1], "기준 시각: 2026-11-17 16:10 KST")
        self.assertNotIn("T07:10:04Z", text)


if __name__ == "__main__":
    unittest.main()
