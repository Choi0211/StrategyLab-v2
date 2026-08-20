"""Patch 8.1 - Persistent Autonomous Research Mission unit tests.

Covers the pure mission-extraction/update/continuation logic in
``gaon.knowledge.research_mission`` in isolation from the full Telegram
conversation stack (that is covered by
``tests/integration/test_persistent_research_mission_conversation.py``).
"""

from __future__ import annotations

import unittest

from gaon.knowledge.research_mission import (
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    add_candidate,
    best_symbol_from_multi_symbol_output,
    clear_focus_symbol,
    distinct_promotion_ready_strategy_count,
    extract_or_update_mission,
    get_active_candidate,
    get_candidate,
    is_candidate_robustness_continuation_request,
    is_cycle_budget_exhausted,
    is_diversity_request,
    is_generic_continuation_request,
    is_provider_acquisition_blocker,
    mission_awaiting_approval_message,
    mission_blocked_message,
    mission_budget_exhausted_message,
    render_mission_candidate_detailed_status,
    next_candidate_sequence,
    next_unexplored_symbols,
    record_blocked,
    record_cycle_result,
    record_focus_symbol,
    record_promotion_candidate,
    update_candidate,
    production_persistent_research_mission_release_check,
)
from gaon.knowledge.strategy_candidate import new_candidate, record_breadth_progress

NOW = "2026-08-17T00:00:00Z"
LATER = "2026-08-17T00:05:00Z"


class MissionExtractionTests(unittest.TestCase):
    def test_no_mission_extracted_from_unrelated_text(self) -> None:
        self.assertIsNone(extract_or_update_mission("안녕하세요", existing=None, now=NOW))

    def test_mission_created_from_first_research_request(self) -> None:
        mission = extract_or_update_mission(
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. 현재 등록되어있는 전략보다 "
            "수익면에서나 안전성 면에서 뛰어나야합니다.",
            existing=None,
            now=NOW,
        )
        self.assertIsNotNone(mission)
        self.assertEqual(mission.market, "KR")
        self.assertTrue(mission.improve_return)
        self.assertTrue(mission.improve_safety)
        self.assertEqual(mission.strategy_family, "short_term_daytrade")
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_market_wide_scope_established_explicitly(self) -> None:
        mission = extract_or_update_mission(
            "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW
        )
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission.market, "KR")
        self.assertIn("KOSPI", mission.exchanges)
        self.assertIn("KOSDAQ", mission.exchanges)

    def test_explicit_multi_symbol_selection_scope(self) -> None:
        mission = extract_or_update_mission(
            "삼성전자와 SK하이닉스를 검증해줘 연구", existing=None, now=NOW
        )
        self.assertEqual(mission.universe_scope, MissionUniverseScope.SELECTED_SYMBOLS)
        self.assertIn("005930", mission.symbols)
        self.assertIn("000660", mission.symbols)

    def test_explicit_multi_symbol_krx_data_request_stays_selected_scope_without_market_wide_scope(self) -> None:
        mission = extract_or_update_mission(
            "아래 5개 종목의 실제 KRX 데이터를 사용해서 여러 종목에서 검증해줘. "
            "005930 삼성전자 000660 SK하이닉스 005380 현대차 035420 NAVER 051910 LG화학",
            existing=None,
            now=NOW,
        )
        self.assertEqual(mission.universe_scope, MissionUniverseScope.SELECTED_SYMBOLS)
        self.assertEqual(mission.symbols, ("005930", "000660", "005380", "035420", "051910"))


class MissionUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. 수익성과 안전성을 개선해주세요.",
            existing=None,
            now=NOW,
        )

    def test_target_candidate_count_persists_once_set(self) -> None:
        updated = extract_or_update_mission(
            "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올때까지 연구해주세요 "
            "삼성만 하지말고 국내 주식 전체를 대상으로 연구해주세요",
            existing=self.mission,
            now=LATER,
        )
        self.assertEqual(updated.target_promotion_ready_candidates, 3)
        self.assertEqual(updated.universe_scope, MissionUniverseScope.MARKET_WIDE)

        # A later, unrelated generic continuation message must not erase the
        # already-established target candidate count.
        again = extract_or_update_mission("증거가 충분할 때까지 연구해주세요", existing=updated, now=LATER)
        self.assertEqual(again.target_promotion_ready_candidates, 3)

    def test_objective_flags_accumulate_across_turns(self) -> None:
        first = extract_or_update_mission("수익률을 개선해주세요 연구", existing=None, now=NOW)
        self.assertTrue(first.improve_return)
        self.assertFalse(first.improve_safety)
        second = extract_or_update_mission("리스크도 줄여주세요 연구", existing=first, now=LATER)
        self.assertTrue(second.improve_return)
        self.assertTrue(second.improve_safety)


class MissionContinuationScopeRegressionTests(unittest.TestCase):
    """The mandatory Patch 8.1 scope-regression guard."""

    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW
        )
        self.assertEqual(self.mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

    def test_generic_continuation_phrase_is_detected(self) -> None:
        for text in (
            "증거가 충분할때까지 다양한방식으로 전략을 연구해주세요",
            "증거가 충분할 때까지 멈추지 말고 연구해주세요",
            "승격가능한게 나올때까지 연구해달라구요",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_generic_continuation_request(text))

    def test_generic_continuation_never_regresses_to_single_symbol(self) -> None:
        # ULTRAREVIEW false-positive repair: market_wide missions always
        # carry an empty `symbols` tuple by construction, so asserting
        # `"005930" not in updated.symbols` would trivially pass even if the
        # regression fully reappeared - the only non-vacuous check is on
        # `universe_scope`/`market` themselves, which is what this asserts.
        for text in (
            "증거가 충분할때까지 다양한방식으로 전략을 연구해주세요",
            "증거가 충분할 때까지 멈추지 말고 연구해주세요",
            "승격가능한게 나올때까지 연구해달라구요",
        ):
            with self.subTest(text=text):
                updated = extract_or_update_mission(text, existing=self.mission, now=LATER)
                self.assertEqual(updated.universe_scope, MissionUniverseScope.MARKET_WIDE)
                self.assertEqual(updated.market, "KR")
                self.assertNotEqual(updated.universe_scope, MissionUniverseScope.SINGLE_SYMBOL)

    def test_generic_continuation_phrase_does_not_override_scope_even_with_a_symbol_name(self) -> None:
        # H3 fix: continuation-preservation takes priority over a symbol
        # mention when the message is ALSO a generic continuation phrase.
        updated = extract_or_update_mission(
            "삼성전자 관련해서 계속 연구해주세요", existing=self.mission, now=LATER
        )
        self.assertEqual(updated.universe_scope, MissionUniverseScope.MARKET_WIDE)

    def test_explicit_single_symbol_override_actually_narrows_the_mission(self) -> None:
        # ULTRAREVIEW false-positive repair: this test previously asserted
        # the OPPOSITE of its own name (that scope stayed market_wide). A
        # real explicit single-symbol directive - naming exactly one symbol,
        # with NO generic-continuation phrasing - must actually narrow an
        # existing broader mission down to that symbol.
        updated = extract_or_update_mission("삼성전자만 다시 연구해", existing=self.mission, now=LATER)
        self.assertEqual(updated.universe_scope, MissionUniverseScope.SINGLE_SYMBOL)
        self.assertEqual(updated.symbols, ("005930",))

    def test_bare_generic_continuation_without_any_symbol_keeps_scope(self) -> None:
        # The guard's core job: a *generic* continuation phrase with no
        # symbol name at all must never narrow scope silently.
        updated = extract_or_update_mission("증거가 충분할 때까지 연구해주세요", existing=self.mission, now=LATER)
        self.assertEqual(updated.universe_scope, MissionUniverseScope.MARKET_WIDE)


class CandidateRobustnessContinuationTests(unittest.TestCase):
    """Patch 8.3 production bug fix: "후보 A 계속 검증해줘" / "OOS 검증해줘"
    / "walk-forward까지 진행해줘" style phrasing must be recognized as a
    mission continuation, not fall through to the legacy single-symbol
    autonomous-research path (which resolves its symbol from stale
    conversational context)."""

    def test_candidate_reference_with_verify_verb_is_a_continuation(self) -> None:
        for text in (
            "후보 A 계속 검증해줘",
            "후보 A를 계속 검증해주세요",
            "그 후보 검증해줘",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_candidate_robustness_continuation_request(text))
                self.assertTrue(is_generic_continuation_request(text))

    def test_named_robustness_stage_with_verb_is_a_continuation(self) -> None:
        for text in (
            "OOS 검증해줘",
            "walk-forward까지 진행해줘",
            "거래비용 스트레스 검증해주세요",
            "시장 국면별 검증 계속 진행해주세요",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_candidate_robustness_continuation_request(text))
                self.assertTrue(is_generic_continuation_request(text))

    def test_patch_8_5_exact_requested_phrases_are_all_continuations(self) -> None:
        # The exact phrase list from the Patch 8.5 production incident
        # report - each of these previously either matched no continuation
        # predicate at all, or matched one that a false-positive tool/
        # intent classifier collision could still defeat (see
        # test_candidate_breadth_to_robustness_transition.py for the full
        # end-to-end reproduction).
        for text in (
            "OOS 검증해주세요",
            "walk-forward 검증해주세요",
            "비용 스트레스 검증해주세요",
            "시장 국면별 검증해주세요",
            "강건성 검증 계속해주세요",
            "다음 검증 단계로 진행해주세요",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_candidate_robustness_continuation_request(text))
                self.assertTrue(is_generic_continuation_request(text))

    def test_bare_candidate_or_topic_mention_without_a_verb_is_not_a_continuation(self) -> None:
        # "후보" or a robustness-stage name alone (no request/continue verb)
        # must not be misread as a continuation - e.g. a pure status
        # question about candidates.
        for text in ("후보 목록 보여줘", "OOS가 뭐야?"):
            with self.subTest(text=text):
                self.assertFalse(is_candidate_robustness_continuation_request(text))

    def test_unrelated_text_is_not_a_continuation(self) -> None:
        self.assertFalse(is_candidate_robustness_continuation_request("안녕하세요"))
        self.assertFalse(is_candidate_robustness_continuation_request("삼성전자 주가 얼마야?"))


class DiversityRequestTargetCountFalsePositiveTests(unittest.TestCase):
    """Patch 8.3 production bug fix: "서로 다른 전략 3개가 준비될 때까지"
    declares the promotion-ready TARGET count's distinctness requirement -
    it must never be misread as a request to rotate away from the
    currently active candidate."""

    def test_distinct_target_count_phrasing_is_not_a_diversity_request(self) -> None:
        for text in (
            "서로 다른 전략 3개가 준비될 때까지 연구해주세요",
            "각기 다른 전략 3개가 모두 나올 때까지 연구해주세요",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_diversity_request(text))

    def test_genuine_rotation_request_is_unaffected(self) -> None:
        for text in ("다른 방식도 찾아봐.", "다른 전략으로 시도해줘", "다른 후보를 찾아봐"):
            with self.subTest(text=text):
                self.assertTrue(is_diversity_request(text))

    def test_rotation_request_stating_a_quantity_is_still_recognized(self) -> None:
        # ULTRAREVIEW fix: an earlier, broader exclusion (bare digit+개,
        # with no "때까지" goal-framing requirement) silently suppressed a
        # genuine immediate rotation request that happens to state a
        # quantity - this must still rotate, unlike a target-count GOAL
        # ("...3개가 준비될 때까지").
        self.assertTrue(is_diversity_request("다른 전략 2개 더 찾아서 계속 연구해줘"))


class MissionCandidateDetailedStatusRenderingTests(unittest.TestCase):
    """Patch 8.5 - the detailed Research Mission + candidate status footer
    must be built only from real persisted state, never fabricated."""

    def test_no_active_candidate_is_rendered_honestly(self) -> None:
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW)
        text = render_mission_candidate_detailed_status(mission, None)
        self.assertIn("active candidate: 없음", text)
        self.assertIn("promotion-ready candidates:", text)

    def test_active_candidate_shows_real_fingerprint_and_stage(self) -> None:
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 수익과 안전성을 개선하는 단타 전략을 연구해주세요", existing=None, now=NOW
        )
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        text = render_mission_candidate_detailed_status(mission, candidate)
        self.assertIn(candidate.candidate_id, text)
        self.assertIn(candidate.strategy_fingerprint[:16], text)
        self.assertIn("candidate stage:", text)
        self.assertIn("promotion-ready candidates:", text)

    def test_never_run_robustness_stages_are_not_run_never_fabricated_pass(self) -> None:
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW)
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        text = render_mission_candidate_detailed_status(mission, candidate)
        self.assertIn("not_run", text)
        self.assertNotIn("PASS", text)
        self.assertNotIn("pass", text.replace("candidates:", "").replace("passed", ""))

    def test_recorded_validation_stage_status_is_shown_verbatim(self) -> None:
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW)
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        from gaon.knowledge.strategy_candidate import record_robustness_progress

        candidate = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=NOW,
            validation_stage_status={"out_of_sample": "not_run_missing_oos_backtest"},
        )
        mission = add_candidate(mission, candidate, now=NOW)
        text = render_mission_candidate_detailed_status(mission, candidate)
        self.assertIn("not_run_missing_oos_backtest", text)


class RobustnessCycleResponseRenderingTests(unittest.TestCase):
    """Patch 8.6 - the candidate-centric robustness-evidence-cycle response
    (real production defect this closes: a market-wide mission's robustness
    response naming the evaluation SYMBOL as the strategy's own identity,
    e.g. "078935 전략을 다시 연구했습니다.", instead of the strategy
    candidate). Every value must come from real persisted state."""

    def setUp(self) -> None:
        from gaon.knowledge.research_mission import render_robustness_cycle_response

        self.render = render_robustness_cycle_response
        self.mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 수익과 안전성을 개선하는 단타 전략을 연구해주세요", existing=None, now=NOW
        )
        self.candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(self.mission), now=NOW)
        self.mission = add_candidate(self.mission, self.candidate, now=NOW)

    def test_candidate_identity_and_evidence_symbol_role_are_both_shown(self) -> None:
        text = self.render(self.candidate, self.mission, symbol="078935")
        self.assertIn(f"[전략 후보 {self.candidate.candidate_id}]", text)
        self.assertIn(self.candidate.strategy_fingerprint[:16], text)
        self.assertIn("symbol=078935", text)
        self.assertIn("역할=evidence sample", text)
        # Never the "SYMBOL 전략을 다시 연구했습니다" shape this patch closes.
        self.assertNotIn("078935 전략을 다시 연구했습니다", text)

    def test_never_run_stages_render_as_not_run_never_fabricated(self) -> None:
        text = self.render(self.candidate, self.mission, symbol="078935")
        self.assertIn("[강건성 상태]", text)
        self.assertIn("not_run", text)
        self.assertNotIn("PASS", text)

    def test_recorded_stage_status_is_shown_verbatim(self) -> None:
        from gaon.knowledge.strategy_candidate import record_robustness_progress

        candidate = record_robustness_progress(
            self.candidate, director_action="collect_more_evidence", terminal=False, now=NOW,
            validation_stage_status={"out_of_sample": "not_run_missing_oos_backtest"}, symbol="078935",
        )
        text = self.render(candidate, self.mission, symbol="078935")
        self.assertIn("not_run_missing_oos_backtest", text)

    def test_mission_footer_shows_real_cumulative_state(self) -> None:
        candidate = record_breadth_progress(
            self.candidate, attempted=10, valid=7, trade_count=42,
            evidence_symbols=("078935", "005380"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        text = self.render(candidate, self.mission, symbol="078935")
        self.assertIn("[Research Mission]", text)
        self.assertIn(f"active candidate: {candidate.candidate_id}", text)
        self.assertIn("cumulative validated symbols: 7", text)
        self.assertIn("cumulative trades: 42", text)
        self.assertIn("promotion-ready: false", text)


class MissionBudgetSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 연구해주세요", existing=None, now=NOW
        )

    def test_budget_exhausted_flag_detection(self) -> None:
        self.assertTrue(is_cycle_budget_exhausted({"adaptive_sampling": {"stop_reason": "research_budget_exhausted"}}))
        self.assertFalse(is_cycle_budget_exhausted({"adaptive_sampling": {"stop_reason": "initial_sample_sufficient"}}))
        self.assertFalse(is_cycle_budget_exhausted({}))

    def test_budget_exhaustion_does_not_complete_the_mission(self) -> None:
        updated = record_cycle_result(self.mission, researched_symbols=("005930", "000660"), now=LATER)
        self.assertEqual(updated.status, MissionStatus.ACTIVE)
        self.assertEqual(updated.cycles_completed, 1)
        self.assertNotEqual(updated.status, MissionStatus.COMPLETED)
        # The mission is still explicit and can continue with unexplored
        # symbols on the next cycle.
        self.assertIn("005930", updated.explored_symbols)

    def test_bounded_execution_one_focus_symbol_at_a_time(self) -> None:
        with_focus = record_focus_symbol(self.mission, symbol="005930", now=LATER)
        self.assertEqual(with_focus.pending_promotion_symbol, "005930")
        cleared = clear_focus_symbol(with_focus, now=LATER)
        self.assertIsNone(cleared.pending_promotion_symbol)

    def test_next_unexplored_symbols_for_selected_universe(self) -> None:
        mission = extract_or_update_mission("삼성전자와 SK하이닉스를 검증해줘 연구", existing=None, now=NOW)
        batch = next_unexplored_symbols(mission, batch_size=5)
        self.assertEqual(set(batch), {"005930", "000660"})
        explored = record_cycle_result(mission, researched_symbols=batch, now=LATER)
        self.assertEqual(next_unexplored_symbols(explored, batch_size=5), ())


class MissionPromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 승격 요청이 가능한 3개의 전략이 나올때까지 연구해주세요",
            existing=None,
            now=NOW,
        )
        self.assertEqual(mission.target_promotion_ready_candidates, 3)
        self.mission = mission

    def test_promotion_candidate_never_invented_below_target(self) -> None:
        updated = record_promotion_candidate(self.mission, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=LATER)
        self.assertEqual(updated.current_promotion_ready_candidates, 1)
        self.assertEqual(updated.status, MissionStatus.ACTIVE)

    def test_reaching_target_requests_human_approval_never_auto_promotes(self) -> None:
        updated = self.mission
        for fingerprint, candidate_id in (("fp-aaa", "KR-ST-001"), ("fp-bbb", "KR-ST-002"), ("fp-ccc", "KR-ST-003")):
            updated = record_promotion_candidate(updated, strategy_fingerprint=fingerprint, candidate_id=candidate_id, now=LATER)
        self.assertEqual(updated.current_promotion_ready_candidates, 3)
        self.assertEqual(updated.status, MissionStatus.AWAITING_HUMAN_APPROVAL)
        message = mission_awaiting_approval_message(updated)
        self.assertIn("자동으로 승격하지 않았습니다", message)

    def test_duplicate_candidate_is_not_double_counted(self) -> None:
        once = record_promotion_candidate(self.mission, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=LATER)
        twice = record_promotion_candidate(once, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=LATER)
        self.assertEqual(twice.current_promotion_ready_candidates, 1)

    def test_same_strategy_on_different_symbols_counts_once(self) -> None:
        # Patch 8.2: the SAME strategy fingerprint validated via different
        # symbols (e.g. a candidate re-validated with a different
        # representative symbol chosen for deep robustness evidence) must
        # never be counted as two promotion-ready candidates - identity is
        # the fingerprint, not the symbol/run_id pair.
        once = record_promotion_candidate(self.mission, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=LATER)
        again_different_run = record_promotion_candidate(once, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=LATER)
        self.assertEqual(again_different_run.current_promotion_ready_candidates, 1)

    def test_distinct_strategy_fingerprints_count_distinctly(self) -> None:
        updated = self.mission
        for fingerprint, candidate_id in (("fp-aaa", "KR-ST-001"), ("fp-bbb", "KR-ST-002")):
            updated = record_promotion_candidate(updated, strategy_fingerprint=fingerprint, candidate_id=candidate_id, now=LATER)
        self.assertEqual(updated.current_promotion_ready_candidates, 2)
        self.assertEqual(distinct_promotion_ready_strategy_count(updated), 2)


class MissionSafeFailureExplanationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 전략이 나올때까지 연구해주세요", existing=None, now=NOW
        )

    def test_budget_exhausted_message_names_mission_and_progress(self) -> None:
        message = mission_budget_exhausted_message(self.mission)
        self.assertIn("연구 목표는 계속 유지", message)
        self.assertIn("종료되지 않았습니다", message)
        self.assertIn("0/3", message)

    def test_blocked_message_states_the_real_reason(self) -> None:
        blocked = record_blocked(self.mission, reason="provider_acquisition_blocker: provider_fetch_failure=15", now=LATER)
        message = mission_blocked_message(blocked)
        self.assertIn("provider_fetch_failure", message)
        self.assertEqual(blocked.status, MissionStatus.BLOCKED)

    def test_provider_acquisition_blocker_detection(self) -> None:
        self.assertTrue(
            is_provider_acquisition_blocker(
                {"total_excluded": 15, "provider_related_excluded": 15}
            )
        )
        self.assertFalse(
            is_provider_acquisition_blocker(
                {"total_excluded": 15, "provider_related_excluded": 2}
            )
        )
        self.assertFalse(is_provider_acquisition_blocker({"total_excluded": 0, "provider_related_excluded": 0}))


class MissionMultiSymbolOutputHelperTests(unittest.TestCase):
    def test_best_symbol_read_from_existing_summary(self) -> None:
        self.assertEqual(best_symbol_from_multi_symbol_output({"summary": {"best_symbol": "005930"}}), "005930")
        self.assertIsNone(best_symbol_from_multi_symbol_output({"summary": {"best_symbol": None}}))
        self.assertIsNone(best_symbol_from_multi_symbol_output({}))


class MissionCandidatePortfolioTests(unittest.TestCase):
    """Patch 8.2 - the mission's strategy candidate portfolio."""

    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW
        )

    def test_add_candidate_becomes_active(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(self.mission), now=NOW)
        updated = add_candidate(self.mission, candidate, now=NOW)
        self.assertEqual(updated.active_candidate_id, candidate.candidate_id)
        self.assertEqual(len(updated.candidates), 1)
        self.assertEqual(get_active_candidate(updated).strategy_family, "breakout_standard")

    def test_second_candidate_gets_a_distinct_sequential_id(self) -> None:
        c1 = new_candidate("breakout_standard", sequence=next_candidate_sequence(self.mission), now=NOW)
        m1 = add_candidate(self.mission, c1, now=NOW)
        c2 = new_candidate("breakout_trend_confirmed", sequence=next_candidate_sequence(m1), now=NOW)
        m2 = add_candidate(m1, c2, now=NOW)
        self.assertEqual(len(m2.candidates), 2)
        self.assertNotEqual(c1.candidate_id, c2.candidate_id)
        self.assertNotEqual(c1.strategy_fingerprint, c2.strategy_fingerprint)
        self.assertEqual(m2.active_candidate_id, c2.candidate_id)

    def test_update_candidate_persists_progress(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(self.mission), now=NOW)
        m1 = add_candidate(self.mission, candidate, now=NOW)
        progressed = record_breadth_progress(
            candidate, attempted=15, valid=12, trade_count=340,
            evidence_symbols=("005930", "000660"), excluded_symbols=("999999",),
            provider_blocked=False, now=LATER,
        )
        m2 = update_candidate(m1, progressed, now=LATER)
        stored = get_candidate(m2, candidate.candidate_id)
        self.assertEqual(stored.valid_symbols, 12)
        self.assertEqual(stored.attempted_symbols, 15)
        self.assertIn("005930", stored.evidence_symbols)

    def test_candidate_portfolio_round_trips_through_mission_json(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(self.mission), now=NOW)
        mission = add_candidate(self.mission, candidate, now=NOW)
        restored = ResearchMission.from_json(mission.to_json())
        self.assertEqual(restored.active_candidate_id, candidate.candidate_id)
        self.assertEqual(get_candidate(restored, candidate.candidate_id).strategy_fingerprint, candidate.strategy_fingerprint)

    def test_pre_patch_8_2_session_metadata_without_candidates_key_degrades_gracefully(self) -> None:
        # A mission persisted by production BEFORE Patch 8.2 has no
        # "candidates"/"active_candidate_id"/"candidate_sequence" keys at
        # all - from_json must not crash on that older shape.
        legacy_json = dict(self.mission.to_json())
        del legacy_json["candidates"]
        del legacy_json["active_candidate_id"]
        del legacy_json["candidate_sequence"]
        restored = ResearchMission.from_json(legacy_json)
        self.assertEqual(restored.candidates, ())
        self.assertIsNone(restored.active_candidate_id)
        self.assertEqual(restored.candidate_sequence, 0)


class MissionPersistenceRoundTripTests(unittest.TestCase):
    def test_to_json_from_json_round_trip(self) -> None:
        from gaon.knowledge.research_mission import ResearchMission

        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 전략이 나올때까지 연구해주세요", existing=None, now=NOW
        )
        # pending_promotion_symbol is only ever set together with an active
        # candidate in production (gaon.runtime.llm_conversation.
        # _try_candidate_breadth_cycle) - a candidate-less
        # pending_promotion_symbol is exactly the legacy shape
        # ResearchMission.from_json's migration clears (see
        # MissionLegacyMigrationTests below), so this round-trip test adds
        # a candidate first to stay realistic.
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        mission = record_focus_symbol(mission, symbol="005930", now=LATER)
        restored = ResearchMission.from_json(mission.to_json())
        self.assertEqual(restored, mission)


class MissionLegacyMigrationTests(unittest.TestCase):
    """ULTRAREVIEW High #3 fix: a mission persisted before Patch 8.2
    introduced strategy_fingerprint-based promotion tracking must load
    safely without letting legacy entries count toward the new target."""

    def _legacy_raw_mission(self, **overrides) -> dict:
        raw = {
            "schema_version": 1,
            "mission_id": "research-mission:legacy",
            "market": "KR",
            "universe_scope": MissionUniverseScope.MARKET_WIDE.value,
            "symbols": [],
            "exchanges": ["KOSPI", "KOSDAQ"],
            "strategy_family": None,
            "objective": {"improve_return": True, "improve_safety": True, "baseline_comparison": "registered_strategy"},
            "target_promotion_ready_candidates": 3,
            "current_promotion_ready_candidates": 3,
            "promotion_ready_candidates": [
                {"symbol": "005930", "run_id": "run-1"},
                {"symbol": "000660", "run_id": "run-2"},
                {"symbol": "473050", "run_id": "run-3"},
            ],
            "explored_symbols": ["005930", "000660", "473050"],
            "status": MissionStatus.AWAITING_HUMAN_APPROVAL.value,
            "blocked_reason": None,
            "cycles_completed": 5,
            "created_at": NOW,
            "updated_at": NOW,
            "originating_request": "국내 주식 전체를 대상으로 연구해주세요",
            "pending_promotion_symbol": "005930",
        }
        raw.update(overrides)
        return raw

    def test_legacy_mission_loads_without_error(self) -> None:
        mission = ResearchMission.from_json(self._legacy_raw_mission())
        self.assertEqual(mission.market, "KR")
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

    def test_legacy_promotion_entries_do_not_inflate_the_patch_8_2_count(self) -> None:
        mission = ResearchMission.from_json(self._legacy_raw_mission())
        self.assertEqual(mission.current_promotion_ready_candidates, 0)
        self.assertEqual(mission.promotion_ready_candidates, ())
        self.assertEqual(distinct_promotion_ready_strategy_count(mission), 0)

    def test_legacy_target_reached_status_reverts_to_active(self) -> None:
        # The raw JSON claims AWAITING_HUMAN_APPROVAL under the OLD
        # (raw-list-length) counting rule - only the verified distinct
        # fingerprint count may authorize that status now.
        mission = ResearchMission.from_json(self._legacy_raw_mission())
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_legacy_pending_promotion_symbol_is_cleared_without_a_candidate_portfolio(self) -> None:
        mission = ResearchMission.from_json(self._legacy_raw_mission())
        self.assertIsNone(mission.pending_promotion_symbol)

    def test_pending_promotion_symbol_survives_migration_when_a_candidate_portfolio_exists(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        raw = self._legacy_raw_mission(
            candidates=[candidate.to_json()], active_candidate_id=candidate.candidate_id, candidate_sequence=1
        )
        mission = ResearchMission.from_json(raw)
        self.assertEqual(mission.pending_promotion_symbol, "005930")

    def test_a_legitimately_verified_fingerprint_entry_still_counts_after_migration(self) -> None:
        raw = self._legacy_raw_mission(
            promotion_ready_candidates=[
                {"symbol": "005930", "run_id": "run-1"},
                {"strategy_fingerprint": "fp-real", "candidate_id": "KR-ST-004", "detected_at": NOW},
            ],
            target_promotion_ready_candidates=2,
        )
        mission = ResearchMission.from_json(raw)
        self.assertEqual(mission.current_promotion_ready_candidates, 1)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)


class MissionDuplicateFingerprintPromotionTests(unittest.TestCase):
    """Duplicate effective rule sets cannot satisfy 3/3 even if candidate
    IDs differ - three different KR-ST-NNN ids sharing one
    strategy_fingerprint must count once."""

    def setUp(self) -> None:
        self.mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 승격 요청이 가능한 3개의 전략이 나올때까지 연구해주세요",
            existing=None,
            now=NOW,
        )

    def test_three_distinct_candidate_ids_sharing_one_fingerprint_never_reach_the_target(self) -> None:
        shared_fingerprint = new_candidate("breakout_standard", sequence=1, now=NOW).strategy_fingerprint
        updated = self.mission
        for candidate_id in ("KR-ST-001", "KR-ST-002", "KR-ST-003"):
            updated = record_promotion_candidate(updated, strategy_fingerprint=shared_fingerprint, candidate_id=candidate_id, now=LATER)
        self.assertEqual(updated.current_promotion_ready_candidates, 1)
        self.assertNotEqual(updated.status, MissionStatus.AWAITING_HUMAN_APPROVAL)

    def test_an_empty_or_unverifiable_fingerprint_is_never_recorded(self) -> None:
        updated = record_promotion_candidate(self.mission, strategy_fingerprint="", candidate_id="KR-ST-001", now=LATER)
        self.assertEqual(updated.current_promotion_ready_candidates, 0)
        self.assertEqual(updated.promotion_ready_candidates, ())


class MissionReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        result = production_persistent_research_mission_release_check()
        self.assertTrue(result["mission_created"])
        self.assertTrue(result["market_wide_scope_preserved"])
        self.assertEqual(result["target_candidates"], 3)
        self.assertTrue(result["scope_regression_blocked"])
        self.assertTrue(result["budget_exhaustion_not_terminal"])
        self.assertTrue(result["bounded_execution_preserved"])
        self.assertTrue(result["human_promotion_gate_preserved"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")


class StrategyCentricReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_strategy_centric_autonomous_research_release_check

        result = production_strategy_centric_autonomous_research_release_check()
        self.assertTrue(result["strategy_candidate_primary_unit"])
        self.assertTrue(result["candidate_fingerprint_symbol_independent"])
        self.assertTrue(result["cross_symbol_validation"])
        self.assertEqual(result["distinct_strategy_target"], 3)
        self.assertTrue(result["symbols_are_evidence_samples"])
        self.assertTrue(result["stagnation_can_rotate_candidate"])
        self.assertTrue(result["baseline_comparison_preserved"])
        self.assertTrue(result["mission_scope_preserved"])
        self.assertTrue(result["bounded_execution_preserved"])
        self.assertTrue(result["human_promotion_gate_preserved"])
        self.assertTrue(result["legacy_migration_safe"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")


class PersistentStrategyCandidateContinuationReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_persistent_strategy_candidate_continuation_release_check

        result = production_persistent_strategy_candidate_continuation_release_check()
        self.assertTrue(result["strategy_candidate_persisted"])
        self.assertTrue(result["candidate_fingerprint_preserved"])
        self.assertTrue(result["stale_symbol_context_blocked"])
        self.assertTrue(result["cross_symbol_identity_preserved"])
        self.assertTrue(result["candidate_rotation"])
        self.assertTrue(result["distinct_promotion_counting"])
        self.assertTrue(result["restart_persistence"])
        self.assertTrue(result["bounded_execution_preserved"])
        self.assertTrue(result["human_promotion_gate_preserved"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")


class CandidateBreadthToRobustnessTransitionReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_candidate_breadth_to_robustness_transition_release_check

        result = production_candidate_breadth_to_robustness_transition_release_check()
        self.assertTrue(result["breadth_to_robustness_transition"])
        self.assertTrue(result["candidate_identity_preserved"])
        self.assertTrue(result["mission_scope_preserved"])
        self.assertTrue(result["no_fabricated_validation_state"])
        self.assertTrue(result["bounded_execution_preserved"])
        self.assertTrue(result["status_ux_reflects_real_state"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.knowledge.research_mission import production_candidate_breadth_to_robustness_transition_release_check

        first = production_candidate_breadth_to_robustness_transition_release_check()
        second = production_candidate_breadth_to_robustness_transition_release_check()
        self.assertEqual(dict(first), dict(second))


class CanonicalCandidateHandoffReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_canonical_candidate_handoff_release_check

        result = production_canonical_candidate_handoff_release_check()
        self.assertTrue(result["report_candidate_canonicalized"])
        self.assertTrue(result["canonical_fingerprint_preserved"])
        self.assertTrue(result["report_label_not_identity"])
        self.assertTrue(result["breadth_to_persisted_candidate"])
        self.assertTrue(result["robustness_uses_same_candidate"])
        self.assertTrue(result["pending_candidate_not_prematurely_rotated"])
        self.assertTrue(result["multi_symbol_robustness_accumulates"])
        self.assertTrue(result["restart_mapping_persists"])
        self.assertTrue(result["status_query_read_only"])
        self.assertTrue(result["ambiguous_candidate_fails_closed"])
        self.assertTrue(result["distinct_promotion_gate_preserved"])
        self.assertTrue(result["bounded_execution_preserved"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.knowledge.research_mission import production_canonical_candidate_handoff_release_check

        first = production_canonical_candidate_handoff_release_check()
        second = production_canonical_candidate_handoff_release_check()
        self.assertEqual(dict(first), dict(second))


class CanonicalResearchReadModelReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_canonical_research_read_model_release_check

        result = production_canonical_research_read_model_release_check()
        self.assertTrue(result["canonical_mission_precedence"])
        self.assertTrue(result["candidate_status_read_only"])
        self.assertTrue(result["candidate_fingerprint_preserved"])
        self.assertTrue(result["candidate_progress_read_only"])
        self.assertTrue(result["strategy_explanation_uses_active_candidate"])
        self.assertTrue(result["strategy_score_read_only"])
        self.assertTrue(result["score_evidence_bound"])
        self.assertTrue(result["stale_context_regression_blocked"])
        self.assertTrue(result["legacy_v5_state_isolated"])
        self.assertTrue(result["research_continuation_still_executes"])
        self.assertTrue(result["same_candidate_after_continuation"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.knowledge.research_mission import production_canonical_research_read_model_release_check

        first = production_canonical_research_read_model_release_check()
        second = production_canonical_research_read_model_release_check()
        self.assertEqual(dict(first), dict(second))


class AutonomousResearchCompletionReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_autonomous_research_completion_release_check

        result = production_autonomous_research_completion_release_check()
        for key in (
            "blocker_driven_progression",
            "passed_validation_not_repeated",
            "duplicate_evidence_blocked",
            "new_evidence_preferred",
            "retest_requires_reason",
            "candidate_progress_persists",
            "stagnation_detected",
            "candidate_rotation_works",
            "candidate_history_preserved",
            "distinct_strategy_identity_preserved",
            "candidate_ranking_evidence_bound",
            "promotion_gate_preserved",
            "distinct_promotion_candidates_counted",
            "three_candidate_target_reachable",
            "three_candidate_target_awaits_human",
            "restart_state_persists",
            "external_provider_status_honest",
            "metadata_only_not_used_as_content",
            "youtube_capability_reported_honestly",
            "bounded_execution_preserved",
            "read_only_zero_tool_calls_preserved",
            "patch87_handoff_preserved",
            "patch88_read_model_preserved",
        ):
            self.assertTrue(result[key], key)
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.knowledge.research_mission import production_autonomous_research_completion_release_check

        first = production_autonomous_research_completion_release_check()
        second = production_autonomous_research_completion_release_check()
        self.assertEqual(dict(first), dict(second))


class ResearchActionExecutionHandoffReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.knowledge.research_mission import production_research_action_execution_handoff_release_check

        result = production_research_action_execution_handoff_release_check()
        for key in (
            "planned_action_consumed",
            "run_regime_actually_executes",
            "action_not_presentation_only",
            "identical_action_replay_blocked",
            "dimension_aware_evidence_identity",
            "retest_requires_reason",
            "actual_progress_semantics",
            "next_action_recomputed",
            "resolved_blocker_not_repeated",
            "no_progress_counts_toward_stagnation",
            "bounded_execution_preserved",
            "patch87_handoff_preserved",
            "patch88_read_model_preserved",
            "autonomous_completion_preserved",
        ):
            self.assertTrue(result[key], key)
        self.assertEqual(result["turn1_action"], "RUN_REGIME")
        self.assertEqual(result["turn2_action_executed"], "RUN_REGIME")
        self.assertNotEqual(result["turn3_next_action"], "RUN_REGIME")
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        from gaon.knowledge.research_mission import production_research_action_execution_handoff_release_check

        first = production_research_action_execution_handoff_release_check()
        second = production_research_action_execution_handoff_release_check()
        self.assertEqual(dict(first), dict(second))


if __name__ == "__main__":
    unittest.main()
