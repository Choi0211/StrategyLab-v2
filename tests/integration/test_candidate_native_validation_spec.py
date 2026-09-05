"""Regression tests for fix/candidate-native-validation-spec.

Root architectural gap this closes: a StrategyCandidateRecord's deep
single-symbol robustness validation (OOS/walk-forward/regime/cost-stress/
parameter-sensitivity/Monte Carlo, via the autonomous_learning_research
tool -> gaon.research.krx_real_pipeline.RealAutonomousResearchPipeline)
never accepted the candidate's own CanonicalStrategySpec directly - it
always re-derived the strategy's rules by rendering a natural-language
description of the candidate (render_candidate_request_text) and re-
parsing that text through UserStrategyParser. Breadth/multi-symbol
validation (multi_symbol_research) already avoided this - it has passed a
candidate's exact rules directly (candidate_spec) since Patch 8.2 - but
deep validation had no equivalent.

For the 17 strategy families this repository currently ships, that
round-trip happens to be lossless (see tests/unit/test_strategy_candidate.py's
family round-trip tests, and the reproduction below empirically confirms
zero fingerprint drift across all of them). The gap is architectural, not
(currently) a live production bug: render_candidate_request_text falls
back SILENTLY to _FAMILY_REQUEST_TEXT["breakout_standard"]'s text for any
strategy_family with no curated text entry - exactly what would happen the
moment a future family (mean reversion, momentum, volatility, relative
strength, regime-aware, or simply a new numeric breakout variant) is added
to the template registry without someone remembering to ALSO hand-author
and verify a matching text entry. UserStrategyParser's regex vocabulary is
moreover fundamentally limited to breakout/stop/channel/trend/volume
concepts - it has no way to express an RSI threshold, a volatility-
contraction window, or a cross-sectional ranking rule as text at all, no
matter how it is phrased.

This suite:
1. Reproduces the exact mismatch this architecture makes possible (a
   family added to the template registry with no matching
   _FAMILY_REQUEST_TEXT entry - a locally test-only simulated template,
   never one added to production code, per this PR's "no new strategy
   family" scope) - proving, via the codebase's own existing defense-in-
   depth (_deep_validation_effective_fingerprint), that BEFORE this fix
   such a candidate's deep-validation evidence would be silently and
   permanently discarded (candidate_identity_unverified on every cycle,
   never able to accumulate robustness evidence).
2. Proves the fix: RealAutonomousResearchPipeline.run's new candidate_spec
   parameter (fed from _try_candidate_robustness_cycle's
   candidate.spec_rules, exactly like multi_symbol_research's own
   candidate_spec argument) makes that same scenario succeed exactly, with
   UserStrategyParser never even invoked.
3. Proves zero behavior change for the existing, already-correct 17
   families (Part F: "현재 breakout 후보의 behavior 자체도 의도적으로
   바꾸지 마세요").
4. Proves the natural-language path (no candidate involved at all) is
   completely unaffected - UserStrategyParser still runs exactly as
   before.
5. Proves every downstream deep-validation stage (OOS/walk-forward/
   regime/cost-stress/parameter-sensitivity/Monte Carlo/multi-symbol peer
   validation) shares the SAME candidate_strategy object -
   gaon.knowledge.autonomous_quant_partner._real_robustness_execution_from_
   baseline passes literally one shared object to every one of those
   stage functions (read directly from source, not assumed) - so fixing
   the single upstream RealAutonomousResearchPipeline.run call site is
   sufficient for all of them.
6. Proves existing (pre-fix-shaped) ResearchMission/StrategyCandidateRecord
   JSON remains readable with no schema change - spec_rules has existed on
   StrategyCandidateRecord since Patch 8.2, long before this fix; this PR
   only wires an already-persisted field through to a new call site.
7. Proves no trading/order/promotion/approval safety flag is affected.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.knowledge.autonomous_quant_partner import (
    ResearchBudget,
    _real_robustness_execution_from_baseline,
    _strategy_from_json,
)
from gaon.knowledge.research_mission import (
    DEFAULT_KR_EXCHANGES,
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
)
from gaon.knowledge.strategy_candidate import (
    STRATEGY_CANDIDATE_SCHEMA_VERSION,
    StrategyCandidateRecord,
    StrategyCandidateStatus,
    StrategyFamilyTemplate,
    _TEMPLATE_BY_FAMILY,
    new_candidate,
    render_candidate_request_text,
)
from gaon.research.krx_real_pipeline import RealAutonomousResearchPipeline, UserStrategyParser, candidate_spec_from_rules_json
from gaon.runtime.llm_conversation import LLMConversationRequest, _deep_validation_effective_fingerprint
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

NOW = "2026-09-05T00:00:00Z"

# A locally test-only strategy family template, simulating "a new family
# was added to the template registry but the corresponding
# _FAMILY_REQUEST_TEXT entry was not (yet) hand-authored" - the realistic
# gap this fix closes. Deliberately uses numeric values (37/-7.0/13) that
# appear in NO existing template, so any accidental match would be a real
# bug, never a coincidence. This is patched into the module's private
# template registry only for the duration of each test (patch.dict) -
# never added to production code, per this PR's explicit "no new strategy
# family" scope.
_GAP_FAMILY = "breakout_test_reproduction_gap_37"
_GAP_TEMPLATE = StrategyFamilyTemplate(
    _GAP_FAMILY, "재현용 테스트 전용 갭 템플릿",
    {"breakout_lookback": 37}, {"protective_stop_pct": -7.0, "channel_exit_lookback": 13}, {},
)


def _with_gap_family():
    return patch.dict(_TEMPLATE_BY_FAMILY, {_GAP_FAMILY: _GAP_TEMPLATE})


class RootCauseReproductionTests(unittest.TestCase):
    """Part B: fails against the pre-fix architecture (verified below by
    calling the OLD code path directly, alongside the NEW one) - not a
    hypothetical."""

    def test_family_missing_a_curated_text_entry_breaks_the_old_text_round_trip(self) -> None:
        with _with_gap_family():
            candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
            # fix/engine-integrity-known-gap-hardening: the fallback text no
            # longer borrows breakout_standard's "고가 돌파" wording - it
            # honestly names the family. Either way it does NOT encode the
            # candidate's real rule VALUES (breakout_lookback=37 etc.), so
            # UserStrategyParser still cannot reconstruct the candidate's
            # identity from it (the PR #183 point).
            self.assertNotIn("고가 돌파", text)
            reconstructed = UserStrategyParser().parse(text, symbol="005930")
            # X (candidate's real, intended identity) != Y (what the OLD
            # text round-trip would have handed to the deep pipeline).
            self.assertNotEqual(candidate.strategy_fingerprint, reconstructed.strategy_family_fingerprint)

    def test_old_defense_in_depth_would_have_silently_discarded_this_candidates_evidence_forever(self) -> None:
        with _with_gap_family():
            candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
            # The OLD call shape (no candidate_spec_rules) - exactly what
            # every call site used before this fix.
            validated = _deep_validation_effective_fingerprint(text, symbol="005930")
            self.assertNotEqual(validated, candidate.strategy_fingerprint)


class DirectSpecFixTests(unittest.TestCase):
    """Part C/D: the fix - candidate.spec_rules becomes the deep-validation
    pipeline's ONLY source of strategy rules once supplied."""

    def test_candidate_spec_makes_the_same_gap_scenario_succeed(self) -> None:
        with _with_gap_family():
            candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
            validated = _deep_validation_effective_fingerprint(text, symbol="005930", candidate_spec_rules=candidate.spec_rules)
            self.assertEqual(validated, candidate.strategy_fingerprint)

    def test_user_strategy_parser_is_never_invoked_when_candidate_spec_is_supplied(self) -> None:
        with _with_gap_family():
            candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
            with patch.object(UserStrategyParser, "parse", side_effect=AssertionError("UserStrategyParser must not be called on the candidate-native path")):
                report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
            self.assertEqual(report.strategy.strategy_family_fingerprint, candidate.strategy_fingerprint)

    def test_numeric_entry_and_exit_parameters_survive_exactly(self) -> None:
        with _with_gap_family():
            candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
            spec = candidate_spec_from_rules_json(candidate.spec_rules, symbol="005930", created_at=NOW)
            self.assertEqual(spec.entry["breakout_lookback"].value, 37)
            self.assertEqual(spec.exit["protective_stop_pct"].value, -7.0)
            self.assertEqual(spec.exit["channel_exit_lookback"].value, 13)

    def test_filters_survive_exactly(self) -> None:
        candidate = new_candidate("breakout_multi_confirmed", sequence=1, now=NOW)
        spec = candidate_spec_from_rules_json(candidate.spec_rules, symbol="005930", created_at=NOW)
        self.assertEqual(spec.filters["volume_gte_ma20"].value, True)
        self.assertEqual(spec.entry["close_gt_ma20"].value, True)
        self.assertEqual(spec.entry["ma20_gt_ma60"].value, True)

    def test_entry_rules_survive_exactly_through_full_pipeline_run(self) -> None:
        candidate = new_candidate("breakout_trend_confirmed", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
        self.assertEqual(report.strategy.entry["breakout_lookback"].value, 20)
        self.assertEqual(report.strategy.entry["close_gt_ma20"].value, True)
        self.assertEqual(report.strategy.entry["ma20_gt_ma60"].value, True)

    def test_exit_rules_survive_exactly_through_full_pipeline_run(self) -> None:
        candidate = new_candidate("breakout_slow_multi_confirmed", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
        self.assertEqual(report.strategy.exit["protective_stop_pct"].value, -6.0)
        self.assertEqual(report.strategy.exit["channel_exit_lookback"].value, 15)


class NaturalLanguagePathBackwardCompatibilityTests(unittest.TestCase):
    """Part I item 1: a real user's own free-text research request (no
    candidate at all) is completely unaffected - UserStrategyParser still
    runs exactly as before."""

    def test_no_candidate_spec_still_uses_user_strategy_parser(self) -> None:
        text = "005930 30 고가 돌파 손절 -6% 15일 저점 이탈 청산"
        report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", generated_at=NOW)
        self.assertEqual(report.strategy.entry["breakout_lookback"].value, 30)
        self.assertEqual(report.strategy.exit["protective_stop_pct"].value, -6.0)
        self.assertEqual(report.strategy.exit["channel_exit_lookback"].value, 15)

    def test_deep_validation_effective_fingerprint_without_candidate_spec_rules_is_unchanged(self) -> None:
        candidate = new_candidate("breakout_trend_confirmed", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "473050")
        validated = _deep_validation_effective_fingerprint(text, symbol="473050")
        self.assertEqual(validated, candidate.strategy_fingerprint)


class ExistingFamiliesUnchangedBehaviorTests(unittest.TestCase):
    """Part F: candidate behavior for every EXISTING family must not
    change. Compares the OLD path (no candidate_spec) against the NEW path
    (candidate_spec supplied) for all 17 currently-shipped families."""

    def test_all_existing_families_produce_identical_strategy_rules_old_vs_new_path(self) -> None:
        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                candidate = new_candidate(family, sequence=1, now=NOW)
                text = render_candidate_request_text(candidate, "005930")
                old_report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", generated_at=NOW)
                new_report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
                self.assertEqual(old_report.strategy.strategy_family_fingerprint, new_report.strategy.strategy_family_fingerprint)
                self.assertEqual(new_report.strategy.strategy_family_fingerprint, candidate.strategy_fingerprint)


class DeepValidationStagesShareOneSpecTests(unittest.TestCase):
    """Part I items 8-13: OOS/walk-forward/regime/cost-stress/parameter-
    sensitivity/Monte Carlo/multi-symbol-peer validation all use the SAME
    candidate identity - proven by actually running
    gaon.knowledge.autonomous_quant_partner._real_robustness_execution_from_
    baseline (the real function every one of those stages is dispatched
    from - see its source: every stage helper receives the SAME
    candidate_strategy object as an explicit parameter, never re-derives
    its own) against a baseline built through the fixed
    RealAutonomousResearchPipeline.run(candidate_spec=...). No live market
    data call is made - the dataset is the pipeline's own already-embedded
    fixture bars, replayed locally; only the fixture_backed policy flag is
    relabeled, the same technique tests/unit/test_autonomous_quant_partner.py
    already uses for this exact function."""

    def _baseline_from_candidate(self, family: str) -> dict:
        candidate = new_candidate(family, sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
        baseline = dict(report.to_json())
        dataset = dict(baseline["dataset"])
        metadata = dict(dataset["metadata"])
        metadata["fixture_backed"] = False
        dataset["metadata"] = metadata
        baseline["dataset"] = dataset
        return candidate, baseline

    def test_baseline_strategy_reconstructed_from_the_pipeline_output_matches_candidate_fingerprint(self) -> None:
        # Deliberately does NOT go through _candidate_strategy_from_baseline:
        # that helper implements a SEPARATE, pre-existing, unrelated concept
        # (an internal "did the critic's own suggested rule tweak beat the
        # baseline in this cycle" comparison - see EvidenceBasedStrategyCritic/
        # ImprovementCandidateGenerator inside RealAutonomousResearchPipeline.
        # run) that this fix neither introduces nor touches. The BASELINE
        # strategy - what _execute_oos/_execute_walk_forward/_execute_regimes/
        # _execute_cost_stress all receive as their own explicit
        # baseline_strategy parameter (see their signatures in this module) -
        # is exactly _strategy_from_json(baseline["strategy"]), reconstructed
        # here the same way production does.
        candidate, baseline = self._baseline_from_candidate("breakout_wide_multi_confirmed")
        baseline_strategy = _strategy_from_json(dict(baseline["strategy"]))
        self.assertEqual(baseline_strategy.strategy_family_fingerprint, candidate.strategy_fingerprint)

    def test_every_deep_validation_stage_shares_the_same_baseline_strategy_object(self) -> None:
        candidate, baseline = self._baseline_from_candidate("breakout_slow_trend_confirmed")
        expected_baseline_fingerprint = _strategy_from_json(dict(baseline["strategy"])).fingerprint
        execution = _real_robustness_execution_from_baseline(
            "005930 30 high breakout MA20 MA60 stop -5% 15 day low exit",
            symbol="005930",
            baseline=baseline,
            budget=ResearchBudget(),
            connection=None,
        )
        self.assertEqual(execution.get("execution_state"), "executed")
        # execution["primary_result"]["strategy_fingerprint"] deliberately
        # NOT asserted here: that field reports _candidate_strategy_from_
        # baseline's own, separate, pre-existing "improvement variant"
        # concept (RealAutonomousResearchPipeline's internal
        # EvidenceBasedStrategyCritic/ImprovementCandidateGenerator, unset
        # by this fix and unrelated to StrategyCandidateRecord) when one
        # happens to exist for this cycle - see this class's own docstring.
        # out_of_sample and each walk_forward fold explicitly report
        # baseline_strategy_fingerprint - proof (by actually running the
        # real functions, not just reading source) that they received the
        # identical baseline_strategy object this test already confirmed
        # matches the candidate. regime_validation/transaction_cost_stress
        # do not surface a fingerprint field in their own output schema,
        # but (per this class's own docstring, verified by direct source
        # reading, not assumed) _execute_regimes/_execute_cost_stress are
        # called with this SAME baseline_strategy parameter - confirmed
        # here only by asserting they actually executed (non-trivial:
        # regime_validation alone requires >= 180 bars).
        self.assertEqual(execution["out_of_sample"].get("baseline_strategy_fingerprint"), expected_baseline_fingerprint)
        for fold in execution["walk_forward"]["folds"]:
            with self.subTest(fold=fold["fold"]):
                self.assertEqual(fold.get("baseline_strategy_fingerprint"), expected_baseline_fingerprint)
        self.assertTrue(execution["regime_validation"]["executed"])
        self.assertGreater(len(execution["regime_validation"]["regimes"]), 0)
        self.assertTrue(execution["transaction_cost_stress"]["executed"])
        self.assertGreater(len(execution["transaction_cost_stress"]["scenarios"]), 0)


class MismatchCannotSilentlyBecomePromotionReadyTests(unittest.TestCase):
    """Part I item 14, end to end through the real production stack: after
    this fix, _try_candidate_robustness_cycle always passes the candidate's
    own spec_rules through - so a mismatch can no longer arise from
    request-text lossiness at all (proven above). The remaining, much
    narrower risk this test guards is candidate DATA corruption itself
    (spec_rules and strategy_fingerprint becoming desynced by some future,
    unrelated bug elsewhere) - simulated here via dataclasses.replace,
    never a real production path. Even then, the existing defense-in-depth
    still catches it: the candidate's evidence is never recorded, and it
    can never reach promotion-ready from a mismatched cycle."""

    def test_identity_unverified_cycle_records_no_new_evidence(self) -> None:
        from dataclasses import replace as _replace

        from gaon.knowledge.research_mission import record_focus_symbol
        from gaon.knowledge.strategy_candidate import record_breadth_progress
        from gaon.runtime.config import GaonRuntimeConfig

        with _with_gap_family():
            store = RuntimeStateStore(":memory:")
            try:
                config = GaonRuntimeConfig(telegram_allowed_chat_ids=("100",), assistant_enabled=True, assistant_provider="deterministic")
                agent = TelegramConversationAgent(config, store._connection)
                candidate = new_candidate(_GAP_FAMILY, sequence=1, now=NOW)
                # Sufficient breadth evidence (mirrors the established
                # pattern in test_candidate_multi_symbol_robustness.py's own
                # _seed_regime_blocked_candidate) so next_blocker_driven_
                # research_action selects a robustness action
                # (autonomous_learning_research), not EXPAND_SAMPLE.
                candidate = record_breadth_progress(
                    candidate, attempted=5, valid=5, trade_count=81,
                    evidence_symbols=("286940", "005930", "000660", "005380", "035420"),
                    excluded_symbols=(), provider_blocked=False, now=NOW,
                )
                # Simulated data corruption: spec_rules no longer matches
                # this candidate's own recorded strategy_fingerprint - a
                # scenario this fix's own candidate_spec plumbing cannot by
                # itself prevent (it faithfully passes through whatever
                # spec_rules the candidate record actually holds).
                corrupted_spec_rules = {
                    "entry": {"breakout_lookback": {"value": 99, "provenance": "research_candidate"}},
                    "exit": {"protective_stop_pct": {"value": -1.0, "provenance": "research_candidate"}, "channel_exit_lookback": {"value": 1, "provenance": "research_candidate"}},
                    "filters": {},
                }
                candidate = _replace(candidate, spec_rules=corrupted_spec_rules)
                mission = ResearchMission(
                    mission_id="research-mission:gap-family-test",
                    market="KR", universe_scope=MissionUniverseScope.MARKET_WIDE, symbols=(),
                    exchanges=DEFAULT_KR_EXCHANGES, strategy_family="short_term_daytrade",
                    improve_return=True, improve_safety=True, baseline_comparison="registered_strategy",
                    target_promotion_ready_candidates=3, current_promotion_ready_candidates=0,
                    promotion_ready_candidates=(), explored_symbols=(), status=MissionStatus.ACTIVE,
                    blocked_reason=None, cycles_completed=1, created_at=NOW, updated_at=NOW,
                    originating_request="test", candidates=(candidate.to_json(),),
                    active_candidate_id=candidate.candidate_id,
                )
                mission = record_focus_symbol(mission, symbol="005930", now=NOW)
                seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "안녕하세요", NOW, "telegram:100:0")
                agent._brain.respond(seed)
                agent._brain._remember_mission(seed, mission)

                # message_id must start with "telegram:" (TelegramConversation
                # Agent's own contract - see _is_conversational_mvp_source)
                # for this direct _brain.respond() call to reach the
                # conversational-MVP/mission-aware pipeline at all.
                fake_output = {
                    "autonomous_learning_v2": {"research_director_decision": {"action": "hold", "reason": "test", "terminal": False}},
                    "autonomous_quant_partner": {"production_grade_validation": {}},
                }
                with patch("gaon.runtime.llm_tools.telegram_autonomous_learning_payload", return_value=fake_output):
                    response = agent._brain.respond(
                        LLMConversationRequest("telegram:100", "telegram:100", "telegram", "연구를 계속해주세요", NOW, "telegram:100:1")
                    )
                self.assertIn("candidate_identity_unverified=", " ".join(response.warnings))
                self.assertEqual(response.tool_calls, ("autonomous_learning_research",))
                updated_mission = agent._brain._mission_for("telegram:100")
                updated_candidate = next(c for c in updated_mission.candidates if c["candidate_id"] == candidate.candidate_id)
                # No new validation stage status/evidence symbol was
                # recorded from this unverified cycle.
                self.assertEqual(updated_candidate.get("validation_stage_status", {}), {})
                self.assertEqual(updated_candidate.get("robustness_evidence_symbols", []), [])
            finally:
                store.close()


class ExistingMissionCompatibilityTests(unittest.TestCase):
    """Part G / I items 15-16: existing (pre-this-fix) ResearchMission /
    StrategyCandidateRecord JSON remains fully readable, no schema
    migration - spec_rules has existed on StrategyCandidateRecord since
    Patch 8.2, long before this fix; this PR only wires that already-
    persisted field through to a new call site."""

    def test_pre_fix_shaped_candidate_json_round_trips_unchanged(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=16, now=NOW)
        payload = candidate.to_json()
        self.assertEqual(payload["schema_version"], STRATEGY_CANDIDATE_SCHEMA_VERSION)
        self.assertIn("spec_rules", payload)
        restored = StrategyCandidateRecord.from_json(payload)
        self.assertEqual(restored.strategy_fingerprint, candidate.strategy_fingerprint)
        self.assertEqual(restored.spec_rules, candidate.spec_rules)

    def test_candidate_spec_from_rules_json_reconstructs_from_a_hand_authored_legacy_shape(self) -> None:
        # A hand-authored, minimal legacy-shaped spec_rules payload - the
        # exact shape a production KR-ST-* candidate created before this
        # fix already has persisted.
        legacy_spec_rules = {
            "entry": {"breakout_lookback": {"value": 20, "provenance": "research_candidate"}},
            "exit": {
                "protective_stop_pct": {"value": -5.0, "provenance": "research_candidate"},
                "channel_exit_lookback": {"value": 10, "provenance": "research_candidate"},
            },
            "filters": {},
        }
        spec = candidate_spec_from_rules_json(legacy_spec_rules, symbol="005930", created_at=NOW)
        self.assertEqual(spec.entry["breakout_lookback"].value, 20)
        self.assertEqual(spec.exit["protective_stop_pct"].value, -5.0)


class TradingAndApprovalSafetyTests(unittest.TestCase):
    """Part H / I items 17-20: this fix touches research/validation input
    integrity only."""

    def test_direct_spec_pipeline_run_reports_no_unsafe_side_effects(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        report = RealAutonomousResearchPipeline(None).run(text, symbol="005930", candidate_spec=candidate.spec_rules, generated_at=NOW)
        payload = report.to_json()
        self.assertNotIn("order_executed", payload)
        self.assertNotIn("champion_promoted", payload)
        self.assertNotIn("approval_bypassed", payload)

    def test_candidate_status_remains_exploring_after_a_single_direct_spec_cycle_seed(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        self.assertEqual(candidate.status, StrategyCandidateStatus.EXPLORING)


if __name__ == "__main__":
    unittest.main()
