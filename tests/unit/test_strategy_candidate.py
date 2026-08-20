"""Patch 8.2 - Strategy Candidate unit tests.

Root cause this patch fixes: production Telegram behavior treated a SYMBOL
(e.g. "473050") as a strategy's identity, so continuation requests kept
re-researching "473050 전략" instead of evaluating one strategy's rules
across many symbols. These tests prove the fix at the unit level; the full
conversation-level fix is covered by
``tests/integration/test_strategy_centric_autonomous_research.py``.
"""

from __future__ import annotations

import unittest

from gaon.research.krx_real_pipeline import UserStrategyParser
from gaon.knowledge.strategy_candidate import (
    ABSOLUTE_CANDIDATE_CYCLE_CAP,
    STRATEGY_FAMILY_TEMPLATES,
    StrategyCandidateStatus,
    build_candidate_spec,
    is_stagnant,
    mark_promotion_ready,
    mark_rejected,
    mark_stagnant,
    new_candidate,
    next_untried_family,
    record_breadth_progress,
    record_robustness_progress,
    render_candidate_block,
    render_candidate_request_text,
    render_candidate_status_summary,
    spec_rules_to_json,
)

NOW = "2026-08-17T00:00:00Z"
LATER = "2026-08-17T00:05:00Z"


class StrategyIdentityIsSymbolIndependentTests(unittest.TestCase):
    """Requirement 1: strategy identity is symbol-independent."""

    def test_same_candidate_on_different_symbols_has_the_same_fingerprint(self) -> None:
        spec_005930 = build_candidate_spec("breakout_trend_confirmed", placeholder_symbol="005930", created_at=NOW)
        spec_000660 = build_candidate_spec("breakout_trend_confirmed", placeholder_symbol="000660", created_at=NOW)
        self.assertEqual(spec_005930.strategy_family_fingerprint, spec_000660.strategy_family_fingerprint)
        # The legacy per-run `.fingerprint` (used elsewhere for dataset/
        # backtest/window matching) is UNCHANGED and remains symbol-
        # dependent - Patch 8.2 adds a new identity, it does not repurpose
        # the old one.
        self.assertNotEqual(spec_005930.fingerprint, spec_000660.fingerprint)

    def test_user_strategy_parser_text_based_specs_are_also_symbol_independent(self) -> None:
        text = "20일 고가 돌파, 종가 > MA20 > MA60, 손절 -5%, 10일 저점 이탈 청산"
        a = UserStrategyParser().parse(text, symbol="005930")
        b = UserStrategyParser().parse(text, symbol="473050")
        self.assertEqual(a.strategy_family_fingerprint, b.strategy_family_fingerprint)

    def test_new_candidate_fingerprint_does_not_depend_on_sequence_number(self) -> None:
        c1 = new_candidate("breakout_standard", sequence=1, now=NOW)
        c2 = new_candidate("breakout_standard", sequence=42, now=NOW)
        self.assertNotEqual(c1.candidate_id, c2.candidate_id)
        self.assertEqual(c1.strategy_fingerprint, c2.strategy_fingerprint)


class DistinctStrategyRulesProduceDistinctFingerprintsTests(unittest.TestCase):
    """Requirement 2: different strategy rules produce distinct fingerprints."""

    def test_every_template_has_a_unique_fingerprint(self) -> None:
        fingerprints = {
            build_candidate_spec(template.family, created_at=NOW).strategy_family_fingerprint
            for template in STRATEGY_FAMILY_TEMPLATES
        }
        self.assertEqual(len(fingerprints), len(STRATEGY_FAMILY_TEMPLATES))

    def test_families_are_named_honestly_within_backtester_capability(self) -> None:
        # Patch 8.2 explicitly must not invent strategy capabilities the
        # backtester does not implement (momentum/mean-reversion/
        # volatility-contraction as separate computations) - every
        # template's rule keys must be within the engine's actual
        # supported vocabulary.
        supported_entry_keys = {"breakout_lookback", "close_gt_ma20", "ma20_gt_ma60"}
        supported_exit_keys = {"protective_stop_pct", "channel_exit_lookback"}
        supported_filter_keys = {"volume_gte_ma20"}
        for template in STRATEGY_FAMILY_TEMPLATES:
            self.assertTrue(set(template.entry.keys()) <= supported_entry_keys, template.family)
            self.assertTrue(set(template.exit.keys()) <= supported_exit_keys, template.family)
            self.assertTrue(set(template.filters.keys()) <= supported_filter_keys, template.family)
            self.assertIn("breakout_lookback", template.entry, template.family)


class NoPerSymbolOptimizationTests(unittest.TestCase):
    """Mandatory requirement: do not optimize strategy parameters per
    symbol for a market-wide mission - the same candidate_spec must be
    reused verbatim regardless of which symbol is being evaluated."""

    def test_spec_rules_json_carries_no_symbol_field(self) -> None:
        spec = build_candidate_spec("breakout_trend_confirmed", placeholder_symbol="005930", created_at=NOW)
        rules = spec_rules_to_json(spec)
        self.assertNotIn("symbol", rules)
        self.assertNotIn("symbol", rules.get("entry", {}))
        self.assertNotIn("symbol", rules.get("exit", {}))
        self.assertEqual(set(rules.keys()), {"entry", "exit", "filters"})

    def test_candidate_spec_is_identical_regardless_of_placeholder_symbol(self) -> None:
        for symbol in ("005930", "000660", "473050", "999999"):
            spec = build_candidate_spec("breakout_multi_confirmed", placeholder_symbol=symbol, created_at=NOW)
            self.assertEqual(
                spec_rules_to_json(spec),
                spec_rules_to_json(build_candidate_spec("breakout_multi_confirmed", placeholder_symbol="005930", created_at=NOW)),
            )


class StagnationRotationTests(unittest.TestCase):
    """Requirement 7: a stagnant candidate rotates to a new strategy
    hypothesis within bounded, deterministic rules."""

    def setUp(self) -> None:
        self.candidate = new_candidate("breakout_standard", sequence=1, now=NOW)

    def test_no_progress_across_threshold_cycles_becomes_stagnant(self) -> None:
        candidate = self.candidate
        # The FIRST call always registers as progress (0 -> 5 valid symbols
        # is a genuine improvement over a freshly created candidate), so
        # STAGNATION_CYCLE_THRESHOLD additional *identical* cycles after
        # that are needed to actually reach the stagnation threshold.
        for _ in range(1 + 3):
            candidate = record_breadth_progress(
                candidate, attempted=15, valid=5, trade_count=200,
                evidence_symbols=(), excluded_symbols=(), provider_blocked=False, now=LATER,
            )
        self.assertTrue(is_stagnant(candidate))

    def test_progress_resets_the_stagnation_counter(self) -> None:
        candidate = self.candidate
        for _ in range(2):
            candidate = record_breadth_progress(
                candidate, attempted=15, valid=5, trade_count=200,
                evidence_symbols=(), excluded_symbols=(), provider_blocked=False, now=LATER,
            )
        self.assertFalse(is_stagnant(candidate))
        progressed = record_breadth_progress(
            candidate, attempted=15, valid=9, trade_count=400,
            evidence_symbols=(), excluded_symbols=(), provider_blocked=False, now=LATER,
        )
        self.assertEqual(progressed.cycles_without_progress, 0)

    def test_provider_blocked_cycles_never_count_toward_stagnation(self) -> None:
        # "Do not reject merely because one provider failed."
        candidate = self.candidate
        for _ in range(10):
            candidate = record_breadth_progress(
                candidate, attempted=15, valid=0, trade_count=0,
                evidence_symbols=(), excluded_symbols=tuple(f"{i:06d}" for i in range(15)),
                provider_blocked=True, now=LATER,
            )
        self.assertEqual(candidate.cycles_without_progress, 0)
        self.assertFalse(is_stagnant(candidate))

    def test_stagnant_candidate_is_excluded_from_next_untried_family_selection(self) -> None:
        stagnant = mark_stagnant(self.candidate, now=LATER)
        family = next_untried_family((stagnant,))
        self.assertNotEqual(family, stagnant.strategy_family)

    def test_next_untried_family_returns_none_once_every_template_is_used(self) -> None:
        candidates = tuple(
            new_candidate(template.family, sequence=index + 1, now=NOW)
            for index, template in enumerate(STRATEGY_FAMILY_TEMPLATES)
        )
        self.assertIsNone(next_untried_family(candidates))

    def test_promotion_ready_and_rejected_candidates_are_never_marked_stagnant(self) -> None:
        promoted = mark_promotion_ready(self.candidate, now=LATER)
        self.assertFalse(is_stagnant(promoted))
        rejected = mark_rejected(self.candidate, reason="bad", now=LATER)
        self.assertFalse(is_stagnant(rejected))


class ValidationStageStatusPersistenceTests(unittest.TestCase):
    """Patch 8.5 - per-stage deep-validation status must be honestly
    persisted (never fabricated) and merged (never silently reset)."""

    def test_new_candidate_has_no_recorded_stage_status(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        self.assertEqual(dict(candidate.validation_stage_status), {})

    def test_stage_status_is_recorded_verbatim(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=LATER,
            validation_stage_status={"out_of_sample": "not_run_missing_oos_backtest", "walk_forward": "not_run_missing_fold_backtests"},
        )
        self.assertEqual(candidate.validation_stage_status["out_of_sample"], "not_run_missing_oos_backtest")
        self.assertEqual(candidate.validation_stage_status["walk_forward"], "not_run_missing_fold_backtests")

    def test_a_later_cycle_touching_only_some_stages_preserves_earlier_ones(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=LATER,
            validation_stage_status={"out_of_sample": "pass"},
        )
        candidate = record_robustness_progress(
            candidate, director_action="run_walk_forward", terminal=False, now=LATER,
            validation_stage_status={"walk_forward": "pass"},
        )
        self.assertEqual(candidate.validation_stage_status["out_of_sample"], "pass")
        self.assertEqual(candidate.validation_stage_status["walk_forward"], "pass")

    def test_round_trips_through_json(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=LATER,
            validation_stage_status={"out_of_sample": "not_run_missing_oos_backtest"},
        )
        from gaon.knowledge.strategy_candidate import StrategyCandidateRecord

        restored = StrategyCandidateRecord.from_json(candidate.to_json())
        self.assertEqual(dict(restored.validation_stage_status), dict(candidate.validation_stage_status))

    def test_legacy_json_without_the_field_degrades_gracefully(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        legacy_json = candidate.to_json()
        del legacy_json["validation_stage_status"]
        from gaon.knowledge.strategy_candidate import StrategyCandidateRecord

        restored = StrategyCandidateRecord.from_json(legacy_json)
        self.assertEqual(dict(restored.validation_stage_status), {})


class CrossSymbolRobustnessEvidenceTests(unittest.TestCase):
    """Patch 8.6: a market-wide mission's robustness stage must accumulate
    evidence across MULTIPLE symbols under one strategy_fingerprint - never
    silently deepen (or lose track of) a single symbol forever."""

    def test_new_candidate_has_no_robustness_evidence(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        self.assertEqual(candidate.robustness_evidence_symbols, ())
        self.assertEqual(candidate.robustness_attempt_count, 0)
        self.assertIsNone(candidate.last_validation_symbol)

    def test_symbol_is_recorded_into_robustness_evidence_symbols(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=LATER, symbol="000660",
        )
        self.assertEqual(candidate.robustness_evidence_symbols, ("000660",))
        self.assertEqual(candidate.robustness_attempt_count, 1)
        self.assertEqual(candidate.last_validation_symbol, "000660")

    def test_repeated_symbol_is_not_duplicated(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=LATER, symbol="000660")
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=LATER, symbol="000660")
        self.assertEqual(candidate.robustness_evidence_symbols, ("000660",))
        self.assertEqual(candidate.robustness_attempt_count, 2)

    def test_robustness_evidence_symbols_are_bounded(self) -> None:
        from gaon.knowledge.strategy_candidate import ROBUSTNESS_EVIDENCE_SYMBOL_CAP

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        for index in range(ROBUSTNESS_EVIDENCE_SYMBOL_CAP + 5):
            candidate = record_robustness_progress(
                candidate, director_action="hold", terminal=True, now=LATER, symbol=f"{100000 + index}",
            )
        self.assertLessEqual(len(candidate.robustness_evidence_symbols), ROBUSTNESS_EVIDENCE_SYMBOL_CAP)

    def test_no_symbol_leaves_evidence_memory_untouched(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=LATER, symbol="000660")
        before = candidate.robustness_evidence_symbols
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=LATER, symbol=None)
        self.assertEqual(candidate.robustness_evidence_symbols, before)
        self.assertEqual(candidate.robustness_attempt_count, 1)
        self.assertEqual(candidate.last_validation_symbol, "000660")

    def test_round_trips_through_json(self) -> None:
        from gaon.knowledge.strategy_candidate import StrategyCandidateRecord

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=LATER, symbol="000660")
        restored = StrategyCandidateRecord.from_json(candidate.to_json())
        self.assertEqual(restored.robustness_evidence_symbols, candidate.robustness_evidence_symbols)
        self.assertEqual(restored.robustness_attempt_count, candidate.robustness_attempt_count)
        self.assertEqual(restored.last_validation_symbol, candidate.last_validation_symbol)

    def test_legacy_json_without_the_fields_degrades_gracefully(self) -> None:
        from gaon.knowledge.strategy_candidate import StrategyCandidateRecord

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        legacy_json = candidate.to_json()
        for key in ("robustness_evidence_symbols", "robustness_attempt_count", "last_validation_symbol", "last_validation_reference"):
            del legacy_json[key]
        restored = StrategyCandidateRecord.from_json(legacy_json)
        self.assertEqual(restored.robustness_evidence_symbols, ())
        self.assertEqual(restored.robustness_attempt_count, 0)
        self.assertIsNone(restored.last_validation_symbol)


class NextRobustnessEvidenceSymbolTests(unittest.TestCase):
    """Patch 8.6: the pure symbol-rotation policy used by
    ``gaon.runtime.llm_conversation._try_candidate_robustness_cycle`` when a
    HOLD (or any other non-promoting, non-rejecting terminal Research
    Director decision) is reached for the current evaluation symbol."""

    def test_picks_first_untried_breadth_evidence_symbol(self) -> None:
        from gaon.knowledge.strategy_candidate import next_robustness_evidence_symbol

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=3, valid=3, trade_count=3,
            evidence_symbols=("000660", "005380", "051910"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        self.assertEqual(next_robustness_evidence_symbol(candidate), "000660")

    def test_skips_symbols_already_used_for_robustness(self) -> None:
        from gaon.knowledge.strategy_candidate import next_robustness_evidence_symbol

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=3, valid=3, trade_count=3,
            evidence_symbols=("000660", "005380", "051910"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=NOW, symbol="000660")
        self.assertEqual(next_robustness_evidence_symbol(candidate), "005380")

    def test_exclude_parameter_skips_the_current_cycle_symbol_too(self) -> None:
        from gaon.knowledge.strategy_candidate import next_robustness_evidence_symbol

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=2, valid=2, trade_count=2,
            evidence_symbols=("000660", "005380"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        # symbol=None means this cycle's evidence was never recorded (e.g.
        # an unverified fingerprint) - exclude= must still prevent an
        # immediate re-pick of the SAME symbol just evaluated.
        self.assertEqual(next_robustness_evidence_symbol(candidate, exclude="000660"), "005380")

    def test_returns_none_once_every_evidence_symbol_is_exhausted(self) -> None:
        from gaon.knowledge.strategy_candidate import next_robustness_evidence_symbol

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=2, valid=2, trade_count=2,
            evidence_symbols=("000660", "005380"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=NOW, symbol="000660")
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=NOW, symbol="005380")
        self.assertIsNone(next_robustness_evidence_symbol(candidate))

    def test_breadth_reentry_selection_exhaustion_requires_sample_expansion(self) -> None:
        """Completion fix: production must not fall back to
        ``evidence_symbols[0]`` after every known evidence symbol has
        already been robustness-tested. Exhaustion returns None so the
        mission can expand breadth evidence on the next bounded turn."""
        from gaon.knowledge.strategy_candidate import next_robustness_evidence_symbol

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=3, valid=3, trade_count=3,
            evidence_symbols=("000660", "005380", "051910"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=NOW, symbol="000660")
        selection = next_robustness_evidence_symbol(candidate)
        self.assertEqual(selection, "005380")

        for symbol in ("005380", "051910"):
            candidate = record_robustness_progress(candidate, director_action="hold", terminal=True, now=NOW, symbol=symbol)
        self.assertIsNone(next_robustness_evidence_symbol(candidate))


class RobustnessProgressTests(unittest.TestCase):
    def test_repeated_identical_director_action_counts_as_no_progress(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        # The first call always registers as progress (None -> an actual
        # action), so 1 + STAGNATION_CYCLE_THRESHOLD identical calls are
        # needed to reach the stagnation threshold.
        for _ in range(1 + 3):
            candidate = record_robustness_progress(candidate, director_action="collect_more_evidence", terminal=False, now=LATER)
        self.assertTrue(is_stagnant(candidate))

    def test_advancing_director_action_alone_is_not_progress(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_robustness_progress(candidate, director_action="collect_more_evidence", terminal=False, now=LATER)
        candidate = record_robustness_progress(candidate, director_action="run_oos", terminal=False, now=LATER)
        self.assertEqual(candidate.cycles_without_progress, 2)

    def test_new_symbol_and_stage_status_are_progress(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=2, valid=2, trade_count=20,
            evidence_symbols=("000660", "005380"), excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        candidate = record_robustness_progress(
            candidate,
            director_action="hold",
            terminal=True,
            validation_stage_status={"walk_forward": "pass"},
            symbol="000660",
            now=LATER,
        )
        self.assertEqual(candidate.cycles_without_progress, 0)
        duplicate = record_robustness_progress(
            candidate,
            director_action="hold",
            terminal=True,
            validation_stage_status={"walk_forward": "pass"},
            symbol="000660",
            now=LATER,
        )
        self.assertEqual(duplicate.robustness_evidence_symbols, ("000660",))
        self.assertEqual(duplicate.cycles_without_progress, 1)

    def test_blocker_driven_action_expands_before_monte_carlo_when_sample_is_small(self) -> None:
        from gaon.knowledge.strategy_candidate import next_blocker_driven_research_action

        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=5, valid=5, trade_count=25,
            evidence_symbols=("005930", "000660", "005380", "035420", "004250"),
            excluded_symbols=(), provider_blocked=False, now=NOW,
        )
        for symbol in candidate.evidence_symbols:
            candidate = record_robustness_progress(
                candidate,
                director_action="hold",
                terminal=True,
                validation_stage_status={
                    "walk_forward": "pass",
                    "regime_validation": "pass",
                    "transaction_cost_stress": "cost_stable",
                    "parameter_sensitivity": "stable",
                    "out_of_sample": "insufficient_oos_sample",
                    "monte_carlo": "not_run_insufficient_primary_sample",
                },
                symbol=symbol,
                now=LATER,
            )
        action, reason = next_blocker_driven_research_action(candidate)
        self.assertEqual(action, "EXPAND_SAMPLE")
        self.assertIn(reason, {"need_new_independent_evidence_symbols", "monte_carlo_waiting_for_primary_sample"})


class UniverseEvidenceSufficiencyTests(unittest.TestCase):
    """1 valid out of 15 attempted cannot support market-wide promotion no
    matter how good that one symbol's result is."""

    def test_single_valid_symbol_out_of_many_is_insufficient(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=15, valid=1, trade_count=40,
            evidence_symbols=("005930",), excluded_symbols=tuple(f"{i:06d}" for i in range(14)),
            provider_blocked=False, now=LATER,
        )
        self.assertFalse(candidate.has_sufficient_universe_evidence)

    def test_broad_valid_coverage_is_sufficient(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=15, valid=12, trade_count=300,
            evidence_symbols=tuple(f"{i:06d}" for i in range(12)), excluded_symbols=(),
            provider_blocked=False, now=LATER,
        )
        self.assertTrue(candidate.has_sufficient_universe_evidence)


class CandidateRenderingTests(unittest.TestCase):
    """Requirement 11: generic market-wide response uses candidate
    identity, not "<symbol> 전략"."""

    def test_candidate_block_uses_candidate_id_not_a_symbol(self) -> None:
        candidate = new_candidate("breakout_trend_confirmed", sequence=17, now=NOW)
        candidate = record_breadth_progress(
            candidate, attempted=15, valid=12, trade_count=300,
            evidence_symbols=("005930", "473050"), excluded_symbols=(),
            provider_blocked=False, now=LATER,
        )
        block = render_candidate_block(candidate)
        self.assertIn("KR-ST-017", block)
        self.assertIn("전략 후보", block)
        self.assertNotIn("473050 전략", block)

    def test_status_summary_reports_distinct_candidate_progress(self) -> None:
        c1 = new_candidate("breakout_standard", sequence=1, now=NOW)
        c2 = new_candidate("breakout_trend_confirmed", sequence=2, now=NOW)
        summary = render_candidate_status_summary((c1, c2), current=0, target=3)
        self.assertIn("KR-ST-001", summary)
        self.assertIn("KR-ST-002", summary)
        self.assertIn("0/3", summary)

    def test_status_summary_with_no_active_candidates_is_still_truthful(self) -> None:
        summary = render_candidate_status_summary((), current=0, target=3)
        self.assertIn("없습니다", summary)
        self.assertIn("0/3", summary)

    def test_candidate_request_text_never_uses_the_symbol_as_the_strategy_name(self) -> None:
        candidate = new_candidate("breakout_volume_confirmed", sequence=5, now=NOW)
        text = render_candidate_request_text(candidate, "473050")
        self.assertIn("473050", text)  # the symbol is legitimate evaluation context
        self.assertNotIn("전략 후보", text)  # but no internal candidate id leaks into the query text


class DeepValidationValidatesTheExactStrategyTests(unittest.TestCase):
    """ULTRAREVIEW High #1 fix: the deep single-symbol validation pipeline
    (gaon.research.krx_real_pipeline.RealAutonomousResearchPipeline) parses
    its strategy from free text via UserStrategyParser - the SAME parser
    used here, never a second implementation. Every supported family's
    request text must round-trip through that exact parser into precisely
    its template's effective rule VALUES, so the fingerprint recorded as
    promotion-ready always represents what was actually deep-validated."""

    def test_every_family_request_text_round_trips_into_the_exact_template_rules(self) -> None:
        for template in STRATEGY_FAMILY_TEMPLATES:
            candidate = new_candidate(template.family, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "473050")
            parsed = UserStrategyParser().parse(text, symbol="473050")
            expected_spec = build_candidate_spec(template.family, placeholder_symbol="473050", created_at=NOW)
            self.assertEqual(
                parsed.strategy_family_fingerprint,
                expected_spec.strategy_family_fingerprint,
                f"{template.family}: deep-validation text round-trip changed the effective rules",
            )

    def test_breakout_standard_request_text_does_not_accidentally_trigger_the_ma20_filter(self) -> None:
        # Root cause of the collapse this fix removes: UserStrategyParser
        # used to treat the bare substring "20일" (used here only to mean
        # "20-day breakout") as also meaning "MA20 trend filter".
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        parsed = UserStrategyParser().parse(text, symbol="005930")
        self.assertNotIn("close_gt_ma20", parsed.entry)
        self.assertNotIn("ma20_gt_ma60", parsed.entry)

    def test_breakout_volume_confirmed_request_text_does_not_accidentally_trigger_the_ma20_filter(self) -> None:
        candidate = new_candidate("breakout_volume_confirmed", sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        parsed = UserStrategyParser().parse(text, symbol="005930")
        self.assertNotIn("close_gt_ma20", parsed.entry)
        self.assertIn("volume_gte_ma20", parsed.filters)

    def test_three_candidate_ids_sharing_one_effective_rule_set_produce_one_fingerprint(self) -> None:
        # A defense-in-depth check for the "3 distinct promotion-ready
        # strategies" requirement: three DIFFERENT candidate objects (as if
        # generated on three different mission turns) that all resolve to
        # the SAME family must never be mistaken for three strategies.
        fingerprints = {
            new_candidate("breakout_standard", sequence=index, now=NOW).strategy_fingerprint
            for index in (1, 5, 9)
        }
        self.assertEqual(len(fingerprints), 1)


class FingerprintProvenanceIndependenceTests(unittest.TestCase):
    """strategy_family_fingerprint must represent effective rule VALUES,
    never FieldProvenance metadata (Probe 1)."""

    def test_identical_values_with_different_provenance_share_a_fingerprint(self) -> None:
        template_spec = build_candidate_spec("breakout_trend_confirmed", created_at=NOW)  # RESEARCH_CANDIDATE provenance
        text = "20 고가 돌파 종가 > MA20 > MA60 손절 -5% 10일 저점 이탈 청산"
        parsed_spec = UserStrategyParser().parse(text, symbol="005930")  # USER_PROVIDED/DEFAULT provenance
        self.assertNotEqual(
            next(iter(template_spec.entry.values())).provenance,
            next(iter(parsed_spec.entry.values())).provenance,
        )
        self.assertEqual(template_spec.strategy_family_fingerprint, parsed_spec.strategy_family_fingerprint)

    def test_a_genuine_rule_difference_still_changes_the_fingerprint(self) -> None:
        # Probe 3: changing an actual strategy rule must change the
        # fingerprint even though provenance is ignored.
        standard = build_candidate_spec("breakout_standard", created_at=NOW)
        trend = build_candidate_spec("breakout_trend_confirmed", created_at=NOW)
        volume = build_candidate_spec("breakout_volume_confirmed", created_at=NOW)
        multi = build_candidate_spec("breakout_multi_confirmed", created_at=NOW)
        fingerprints = {spec.strategy_family_fingerprint for spec in (standard, trend, volume, multi)}
        self.assertEqual(len(fingerprints), 4)


class AbsoluteCandidateCycleCapTests(unittest.TestCase):
    def test_absolute_cycle_cap_forces_stagnation_even_with_oscillating_progress(self) -> None:
        # A Research Director alternating between two actions every cycle
        # would otherwise reset cycles_without_progress to 0 forever
        # (record_robustness_progress treats any action CHANGE as
        # progress) - the absolute cap is the hard backstop.
        candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
        for index in range(ABSOLUTE_CANDIDATE_CYCLE_CAP + 1):
            action = "collect_more_evidence" if index % 2 == 0 else "run_oos"
            candidate = record_robustness_progress(candidate, director_action=action, terminal=False, now=LATER)
        self.assertTrue(is_stagnant(candidate))


if __name__ == "__main__":
    unittest.main()
