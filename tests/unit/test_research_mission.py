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
    is_cycle_budget_exhausted,
    is_generic_continuation_request,
    is_provider_acquisition_blocker,
    mission_awaiting_approval_message,
    mission_blocked_message,
    mission_budget_exhausted_message,
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


if __name__ == "__main__":
    unittest.main()
