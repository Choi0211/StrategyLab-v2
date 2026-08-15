from __future__ import annotations

import unittest

from gaon.runtime.llm_conversation import (
    _autonomous_learning_execution_text,
    _autonomous_learning_request_mode,
    _autonomous_request_mode,
    _has_explicit_autonomous_learning_v2_intent,
    _is_fresh_autonomous_learning_execution_request,
    _should_use_promotion_candidate_presentation,
)


FRESH_RESEARCH = (
    "가온아 삼성전자 전략을 처음부터 다시 연구해줘.\n"
    "실제 시장 데이터와 현재 사용 가능한 외부 provider를 모두 사용해서 조사하고, 각 provider의 성공·실패 상태도 기록해줘.\n"
    "기존 OOS, walk-forward, 거래비용 등의 검증 실패를 다음 후보 연구에 실제로 반영해서 새 후보를 만들고 재검증해줘.\n"
    "이전에 검증한 것과 동일한 후보는 반복하지 말고 fingerprint로 차단해줘.\n"
    "충분히 검증된 후보가 나와도 자동 교체하지 말고 1차 승인 요청에서 멈춰줘."
)

LEGACY_APPROVAL_RESEARCH = (
    "삼성전자 전략을 처음부터 다시 연구해줘.\n"
    "외부 연구 자료도 찾아보고,\n"
    "지금까지 배운 내용과 실제 시장 데이터를 사용해서\n"
    "문제점을 찾고 개선 전략 후보를 만든 뒤 검증해줘.\n"
    "좋은 전략 후보가 생기면 승격 승인을 요청하기 전까지 진행해줘."
)

PROMOTION_DETAIL = (
    "아직 승인하지 않을게. 지금 생성한 승격 후보를 자세히 설명해줘. "
    "후보 ID와 fingerprint, 기존 전략에서 무엇이 바뀌었는지, 연구 가설, "
    "참고한 외부 자료와 출처, 실제 백테스트 결과, 검증 결과, 랭킹 근거, 주요 위험을 보여줘. "
    "근거가 없는 숫자는 만들지 말고 승인이나 전략 변경도 하지 마."
)


class FreshAutonomousLearningRequestRoutingTests(unittest.TestCase):
    def test_fresh_restart_preempts_internal_continue_and_approval_language(self) -> None:
        text = (
            "\uac00\uc628\uc544 \uc0bc\uc131\uc804\uc790 \uc804\ub7b5\uc744 "
            "\ucc98\uc74c\ubd80\ud130 \ub2e4\uc2dc \uc5f0\uad6c\ud574\uc918.\n"
            "\uc2e4\uc81c \uc2dc\uc7a5 \ub370\uc774\ud130\uc640 provider\ub97c "
            "\uc0ac\uc6a9\ud574\uc11c \uc870\uc0ac\ud574\uc918.\n"
            "\uae30\uc874 OOS, walk-forward, \uac70\ub798\ube44\uc6a9 "
            "\uac80\uc99d \uc2e4\ud328\ub97c \ub2e4\uc74c \ud6c4\ubcf4 "
            "\uc5f0\uad6c\uc5d0 \ubc18\uc601\ud558\uace0 \uc7ac\uac80\uc99d\ud574\uc918.\n"
            "\uc774\uc804\uc5d0 \uac80\uc99d\ud55c \ud6c4\ubcf4\ub294 fingerprint\ub85c "
            "\ucc28\ub2e8\ud574\uc918.\n"
            "\ud55c \ud6c4\ubcf4\uac00 \uc2e4\ud328\ud558\uba74 \uac19\uc740 "
            "\uc694\uccad \uc548\uc5d0\uc11c \ub2e4\uc74c \ud6c4\ubcf4\ub97c "
            "\uacc4\uc18d \uc5f0\uad6c\ud574\uc918.\n"
            "\uc790\ub3d9 \uad50\uccb4\ud558\uc9c0 \ub9d0\uace0 1\ucc28 "
            "\uc2b9\uc778 \uc694\uccad\uc5d0\uc11c \uba48\ucdb0\uc918."
        )

        self.assertEqual("research", _autonomous_learning_request_mode(text))
        self.assertEqual("validate", _autonomous_request_mode(text))
        self.assertTrue(_has_explicit_autonomous_learning_v2_intent(text))
        self.assertTrue(_is_fresh_autonomous_learning_execution_request(text))
        self.assertFalse(_should_use_promotion_candidate_presentation(text))


    def test_new_live_research_contract_runs_as_fresh_research(self) -> None:
        self.assertIn(
            _autonomous_learning_request_mode(FRESH_RESEARCH),
            {"research", "external_research"},
        )
        self.assertTrue(_is_fresh_autonomous_learning_execution_request(FRESH_RESEARCH))

    def test_legacy_approval_boundary_contract_remains_approval_review(self) -> None:
        self.assertEqual(
            "approval_review",
            _autonomous_learning_request_mode(LEGACY_APPROVAL_RESEARCH),
        )
        self.assertFalse(
            _is_fresh_autonomous_learning_execution_request(LEGACY_APPROVAL_RESEARCH)
        )

    def test_promotion_detail_with_fingerprint_remains_presentation_only(self) -> None:
        self.assertTrue(_should_use_promotion_candidate_presentation(PROMOTION_DETAIL))
        self.assertFalse(_is_fresh_autonomous_learning_execution_request(PROMOTION_DETAIL))

    def test_fresh_research_uses_current_request_not_previous_context(self) -> None:
        mode = _autonomous_learning_request_mode(FRESH_RESEARCH)
        self.assertIn(mode, {"research", "external_research"})
        assert mode is not None
        self.assertEqual(
            FRESH_RESEARCH,
            _autonomous_learning_execution_text(
                FRESH_RESEARCH,
                previous_text="삼성전자 전략 다시 연구해줘",
                mode=mode,
            ),
        )

    def test_continuation_preserves_previous_research_contract(self) -> None:
        previous = "삼성전자 전략을 처음부터 다시 연구해줘. 외부 자료도 찾아줘."
        self.assertEqual(
            previous,
            _autonomous_learning_execution_text(
                "계속 연구해줘",
                previous_text=previous,
                mode="continue",
            ),
        )

    def test_standalone_approval_request_remains_approval_review(self) -> None:
        self.assertEqual(
            "approval_review",
            _autonomous_learning_request_mode("승격 승인 요청해줘"),
        )


if __name__ == "__main__":
    unittest.main()
