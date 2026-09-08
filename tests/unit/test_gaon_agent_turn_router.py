"""Gaon Agent Foundation V2 - turn router classification unit tests."""

from __future__ import annotations

import unittest

from gaon.runtime.gaon_agent import GaonTurnRouter, TurnLane, default_capability_registry
from gaon.runtime.gaon_agent.multimodal import Modality


class GaonTurnRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = GaonTurnRouter(default_capability_registry())

    def test_plain_conversation_passes_through(self) -> None:
        for text in ("이름이 뭐예요?", "재밌는 이야기 해줘", "우주는 왜 어두워요?", "너는 어떻게 생각해?"):
            self.assertEqual(self.router.classify(text).lane, TurnLane.PASS_THROUGH)

    def test_url_without_fetch_capability_is_a_limitation(self) -> None:
        routed = self.router.classify("이 게시물 어때요? https://www.instagram.com/p/abc123/")
        self.assertEqual(routed.lane, TurnLane.URL_LIMITATION)
        self.assertIn("링크를 직접 열어", routed.text)
        self.assertNotIn("확인했습니다", routed.text)
        # bare social domain, no scheme
        self.assertEqual(
            self.router.classify("youtube.com/watch?v=x 이거 봐봐").lane,
            TurnLane.MULTIMODAL_LIMITATION,  # "영상" implied by youtube + 봐봐 -> video modality wins
        )

    def test_current_info_without_live_provider_is_a_limitation(self) -> None:
        for text in ("오늘 날씨는 어때요?", "지금 비트코인 가격 얼마야?", "현재 환율 얼마예요?"):
            routed = self.router.classify(text)
            self.assertEqual(routed.lane, TurnLane.CURRENT_INFO_LIMITATION, text)
            self.assertIn("실시간 정보", routed.text)

    def test_research_topic_is_not_mistaken_for_current_info(self) -> None:
        routed = self.router.classify("비트코인 단타 전략 연구해줘")
        self.assertEqual(routed.lane, TurnLane.PASS_THROUGH)

    def test_media_inspect_request_is_a_limitation(self) -> None:
        routed = self.router.classify("이 차트 스크린샷 좀 분석해줘")
        self.assertEqual(routed.lane, TurnLane.MULTIMODAL_LIMITATION)
        self.assertEqual(routed.modality, Modality.IMAGE)
        self.assertIn("이미지", routed.text)

    def test_multi_question_turn_is_multi_intent(self) -> None:
        routed = self.router.classify("이름이뭔가요\n\n단타 전략 연구가 승격될만한게 나오려면 뭐가 필요할까요")
        self.assertEqual(routed.lane, TurnLane.MULTI_INTENT)
        self.assertEqual(len(routed.segments), 2)

    def test_structured_research_brief_is_not_split(self) -> None:
        brief = (
            "가온아 아래 종목의 실제 KRX 데이터를 사용해서 다중종목 연구해줘.\n\n"
            "대상 종목:\n005930 삼성전자\n000660 SK하이닉스\n\n"
            "연구 기간:\n2021-07-25 ~ 2026-07-24\n\n"
            "전략:\n20일 고가 돌파\n종가 > MA20 > MA60\n\n"
            "모든 종목에 동일한 전략과 동일한 백테스트 가정을 적용해줘."
        )
        routed = self.router.classify(brief, allow_multi=False)
        self.assertEqual(routed.lane, TurnLane.PASS_THROUGH)

    def test_defer_keeps_a_single_turn_with_the_existing_pipeline(self) -> None:
        routed = self.router.classify("활성 후보 상태 알려줘", defer=True)
        self.assertEqual(routed.lane, TurnLane.PASS_THROUGH)


if __name__ == "__main__":
    unittest.main()
