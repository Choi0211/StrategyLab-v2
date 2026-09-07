"""PR #213 - conversation-integrity layer unit tests.

Covers the deterministic INTERPRET / AUTHORIZE stages
(``gaon.runtime.conversation_integrity``) and the centralized
blocker-reason -> user-facing-Korean path
(``gaon.knowledge.research_mission.render_blocked_reason_explanation`` /
``mission_blocked_message`` / ``wants_technical_blocker_detail``).
"""

from __future__ import annotations

import unittest

from gaon.runtime.conversation_integrity import (
    authorizes_state_changing_research,
    is_read_only_conversation,
    read_only_intent,
    read_only_turn_may_not_mutate_mission,
)
from gaon.knowledge.research_mission import (
    blocked_reason_code,
    mission_blocked_message,
    record_blocked,
    extract_or_update_mission,
    render_blocked_reason_explanation,
    wants_technical_blocker_detail,
)

_RAW = "strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted"


class ReadOnlyIntentClassification(unittest.TestCase):
    READ_ONLY = [
        "왜?",
        "왜 그렇게 됐어?",
        "그게 무슨 뜻이야?",
        "쉽게 설명해줘",
        "한글로 설명해줘",
        "이유를 한글로 알아들을수있게 말해주세요",
        "이유를 말해줘",
        "현재 진행상황 알려줘",
        "그중 제일 좋은 건?",
        "왜 그게 제일 좋아?",
        "그 후보는 왜 탈락했어?",
        "그거 더 자세히 설명해줘",
        "그 연구는 아직 막혀 있어?",
        "그래서 지금 내가 결정해야 할 게 있어?",
        "이 상태면 다음엔 뭘 연구하는 게 좋아?",
        "요약해줘",
        "바이낸스 쪽은?",
    ]
    RESEARCH = [
        "삼성전자 전략을 다시 연구해줘",
        "이 후보를 더 연구해줘",
        "새 후보 만들어서 검증해줘",
        "이 전략을 재검증해줘",
        "그거 더 연구해줘",
    ]

    def test_read_only_phrasings_classify_as_read_only(self) -> None:
        for text in self.READ_ONLY:
            with self.subTest(text=text):
                self.assertTrue(is_read_only_conversation(text), text)
                self.assertFalse(authorizes_state_changing_research(text), text)

    def test_research_requests_are_not_read_only(self) -> None:
        for text in self.RESEARCH:
            with self.subTest(text=text):
                self.assertTrue(authorizes_state_changing_research(text), text)
                self.assertFalse(is_read_only_conversation(text), text)

    def test_explanation_is_never_inferred_as_research(self) -> None:
        # The critical rule: "please explain" must never be read as
        # "please research again".
        self.assertFalse(authorizes_state_changing_research("이유를 한글로 알아들을수있게 말해주세요"))
        self.assertTrue(read_only_turn_may_not_mutate_mission("이유를 한글로 알아들을수있게 말해주세요"))

    def test_read_only_intent_kinds(self) -> None:
        self.assertEqual(read_only_intent("왜?"), "why")
        self.assertEqual(read_only_intent("그게 무슨 뜻이야?"), "clarify")
        self.assertEqual(read_only_intent("한글로 설명해줘"), "translate")
        self.assertEqual(read_only_intent("그중 제일 좋은 건?"), "compare")
        self.assertIsNone(read_only_intent("삼성전자와 SK하이닉스 관계를 서술하라"))

    def test_stop_request_is_not_a_read(self) -> None:
        self.assertFalse(is_read_only_conversation("연구 중단해주세요"))

    def test_paradigm_selection_and_diversity_stay_directional(self) -> None:
        # A9 paradigm selection / diversity rotation are directional
        # instructions, not "explain the previous answer" - they keep their
        # existing mission-continuation routing.
        self.assertFalse(read_only_turn_may_not_mutate_mission("평균회귀 전략은 어때?"))
        self.assertFalse(read_only_turn_may_not_mutate_mission("다른 방식도 찾아봐"))


class CentralizedBlockedReasonExplanation(unittest.TestCase):
    def test_known_code_renders_natural_korean_without_raw_code(self) -> None:
        text = render_blocked_reason_explanation(_RAW)
        self.assertIn("더 확장할 후보가 남아 있지 않아", text)
        self.assertNotIn("strategy_hypothesis_space_exhausted", text)
        self.assertNotIn("bounded declarative", text)

    def test_technical_flag_appends_raw_code(self) -> None:
        text = render_blocked_reason_explanation(_RAW, technical=True)
        self.assertIn("더 확장할 후보가 남아 있지 않아", text)
        self.assertIn(_RAW, text)

    def test_unknown_code_is_conservative_and_keeps_raw_handle(self) -> None:
        text = render_blocked_reason_explanation("some_unheard_of_blocker: internal detail")
        self.assertIn("알려진 사유 목록에 없는", text)
        self.assertIn("some_unheard_of_blocker: internal detail", text)
        # never fabricates a specific explanation for an unknown code
        self.assertNotIn("더 확장할 후보", text)

    def test_none_reason_is_stated_plainly(self) -> None:
        self.assertIn("기록되어 있지 않", render_blocked_reason_explanation(None))

    def test_blocked_reason_code_key_extraction(self) -> None:
        self.assertEqual(blocked_reason_code(_RAW), "strategy_hypothesis_space_exhausted")
        self.assertEqual(blocked_reason_code("selected_symbol_universe_exhausted"), "selected_symbol_universe_exhausted")
        self.assertIsNone(blocked_reason_code(None))

    def test_wants_technical_detail_detection(self) -> None:
        for text in ["내부 코드로 알려줘", "raw status 보여줘", "디버그 정보 줘", "blocker 코드 그대로"]:
            self.assertTrue(wants_technical_blocker_detail(text), text)
        for text in ["왜 멈췄어?", "쉽게 설명해줘", "현재 상태 알려줘"]:
            self.assertFalse(wants_technical_blocker_detail(text), text)

    def test_mission_blocked_message_hides_raw_code_by_default(self) -> None:
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now="2026-09-07T00:00:00Z")
        blocked = record_blocked(mission, reason=_RAW, now="2026-09-07T00:00:00Z")
        default_text = mission_blocked_message(blocked)
        self.assertNotIn("strategy_hypothesis_space_exhausted", default_text)
        self.assertIn("더 확장할 후보가 남아 있지 않아", default_text)
        technical_text = mission_blocked_message(blocked, technical=True)
        self.assertIn(_RAW, technical_text)


if __name__ == "__main__":
    unittest.main()
