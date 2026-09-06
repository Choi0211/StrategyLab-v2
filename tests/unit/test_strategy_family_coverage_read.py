"""Unit coverage for the strategy-family-coverage read (fix/web-
conversation-family-coverage-read): the predicate that recognises "돌파
말고 다른 전략도 연구하고 있어?" as a READ question (not a rotation
command), and the renderer that answers it truthfully from persisted
state only."""

from __future__ import annotations

import unittest

from gaon.knowledge.research_mission import (
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    add_candidate,
    extract_or_update_mission,
    is_diversity_request,
    is_strategy_family_coverage_question,
    next_candidate_sequence,
    render_mission_family_coverage,
    set_active_candidate,
)
from gaon.knowledge.strategy_candidate import new_candidate

NOW = "2026-09-07T00:00:00Z"


class FamilyCoverageQuestionPredicateTests(unittest.TestCase):
    def test_true_for_read_questions(self) -> None:
        for text in (
            "돌파 말고 다른 전략도 연구하고 있어?",
            "돌파 말고 다른 전략도 연구하고 있어? readonly",
            "그중에서 상대강도 전략은?",
            "평균회귀나 모멘텀 전략도 연구 중이야?",
            "비돌파 전략도 있어?",
        ):
            self.assertTrue(is_strategy_family_coverage_question(text), text)

    def test_false_for_rotation_commands_single_paradigm_a9_and_unrelated_text(self) -> None:
        for text in (
            "다른 방식도 찾아봐",
            "다른 전략 2개 더 찾아봐",
            "평균회귀 전략으로 연구해줘",
            "모멘텀 전략도 비교해줘",
            # single-paradigm A9 selection - requested_strategy_family owns these
            "평균회귀 전략은 어때?",
            "국면 필터 전략은 어때?",
            "단타 연구 잘되고 있어?",
            "그중 제일 좋은 건?",
            "증거가 충분할 때까지 연구해주세요",
            "",
        ):
            self.assertFalse(is_strategy_family_coverage_question(text), text)

    def test_rotation_commands_still_match_is_diversity_request(self) -> None:
        self.assertTrue(is_diversity_request("다른 방식도 찾아봐"))
        self.assertTrue(is_diversity_request("다른 전략 2개 더 찾아봐"))


def _mission(families: list[str], *, with_active: bool, symbols: tuple[str, ...] = ()) -> ResearchMission:
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
    if symbols:
        mission = ResearchMission.from_json({**mission.to_json(), "symbols": list(symbols), "universe_scope": MissionUniverseScope.SELECTED_SYMBOLS.value})
    last = None
    for family in families:
        candidate = new_candidate(family, sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        last = candidate.candidate_id
    if with_active and last is not None:
        mission = set_active_candidate(mission, last, now=NOW)
    return mission


class RenderMissionFamilyCoverageTests(unittest.TestCase):
    def test_names_families_with_candidates_and_marks_the_rest_as_directions(self) -> None:
        text = render_mission_family_coverage(
            _mission(["breakout_standard", "mean_reversion_standard"], with_active=True)
        )
        self.assertIn("breakout_standard", text)
        self.assertIn("mean_reversion_standard", text)
        self.assertIn("momentum_roc_standard", text)
        self.assertIn("volatility_thrust_standard", text)
        self.assertIn("연구 방향", text)  # families with no candidate
        # never claims a family with no candidate is being researched
        self.assertNotIn("momentum_roc_standard(momentum_roc_standard): 후보 있음", text)

    def test_relative_strength_fail_closed_without_explicit_peer_context(self) -> None:
        text = render_mission_family_coverage(_mission(["breakout_standard"], with_active=True))
        self.assertIn("relative_strength_requires_multi_symbol_context", text)
        self.assertIn("가짜 peer", text)

    def test_relative_strength_available_direction_with_explicit_peers(self) -> None:
        text = render_mission_family_coverage(
            _mission(["breakout_standard"], with_active=True, symbols=("005930", "000660"))
        )
        self.assertNotIn("relative_strength_requires_multi_symbol_context", text)
        self.assertIn("다음 로테이션", text)

    def test_no_candidates_at_all_is_reported_honestly(self) -> None:
        text = render_mission_family_coverage(_mission([], with_active=False))
        self.assertIn("생성된 전략 후보가 없습니다", text)

    def test_never_invents_a_candidate_id(self) -> None:
        text = render_mission_family_coverage(_mission(["breakout_standard"], with_active=True))
        # exactly one candidate id (KR-ST-001) appears
        self.assertEqual(text.count("KR-ST-"), 1)


if __name__ == "__main__":
    unittest.main()
