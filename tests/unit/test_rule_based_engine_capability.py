"""fix/rule-based-engine-fail-closed: RuleBasedBacktestEngine must reject a
CanonicalStrategySpec it cannot fully interpret, before it executes
anything.

Root architectural gap (confirmed against main, read-only, before this
branch): gaon.research.krx_real_pipeline.RuleBasedBacktestEngine.run reads
a fixed, hard-coded set of rule keys -
entry: breakout_lookback (dereferenced with [], bare KeyError if absent),
       close_gt_ma20 / ma20_gt_ma60 (via .get(), optional);
exit:  protective_stop_pct ([], bare KeyError if absent),
       channel_exit_lookback (.get() defaulting to 10);
filters: volume_gte_ma20 (.get(), optional)
- and SILENTLY IGNORES every other key. A CanonicalStrategySpec carrying,
e.g., an "rsi_below" entry rule plus a "breakout_lookback" produces a
result byte-for-byte identical to the pure-breakout spec: the RSI rule is
dropped without any error, and a valid-looking research result is
recorded for a strategy the engine never actually ran. There is no
explicit capability contract anywhere - the "grammar" is implicit in
which dict keys the run() method happens to read.

After PR #183 candidate.spec_rules reaches the engine exactly; this
branch makes the engine fail closed on anything it cannot interpret, so
"the rules the candidate intended" can never diverge from "the behaviour
the engine executed" via silent rule-dropping.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.knowledge.strategy_candidate import (
    _FAMILY_REQUEST_TEXT,
    _TEMPLATE_BY_FAMILY,
    build_candidate_spec,
)
from gaon.research.krx_real_pipeline import (
    RULE_BASED_BACKTEST_CAPABILITIES,
    RULE_BASED_ENGINE_NAME,
    CanonicalStrategySpec,
    FieldProvenance,
    KRXFixtureMarketDataProvider,
    PerformanceMetricsCalculator,
    ProvenancedValue,
    RuleBasedBacktestCapabilities,
    RuleBasedBacktestEngine,
    UnsupportedStrategyRuleError,
    UnsupportedStrategySpecError,
    UserStrategyParser,
    default_execution_assumptions,
    validate_strategy_spec_for_rule_based_engine,
)

NOW = "2026-07-25T00:00:00Z"


def _v(value):
    return ProvenancedValue(value, FieldProvenance.RESEARCH_CANDIDATE)


def _spec(entry, exit_rules, filters):
    return CanonicalStrategySpec("canonical-strategy:test", "005930", dict(entry), dict(exit_rules), dict(filters), "test", NOW)


_SUPPORTED_BREAKOUT_ENTRY = {"breakout_lookback": _v(20)}
_SUPPORTED_EXIT = {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}


def _dataset():
    return KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")


def _run(spec):
    return RuleBasedBacktestEngine().run("unit-run", spec, _dataset(), default_execution_assumptions(), generated_at=NOW)


class UnsupportedFamilyRejectedTests(unittest.TestCase):
    def test_a_fully_non_breakout_spec_is_rejected_not_run_as_breakout(self) -> None:
        spec = _spec({"rsi_below": _v(30)}, {"rsi_above": _v(70)}, {})
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(spec)


class UnsupportedEntryRuleRejectedTests(unittest.TestCase):
    def test_unknown_entry_rule_alongside_a_supported_one_is_rejected(self) -> None:
        spec = _spec({**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30)}, _SUPPORTED_EXIT, {})
        with self.assertRaises(UnsupportedStrategyRuleError) as ctx:
            _run(spec)
        self.assertIn("rsi_below", str(ctx.exception))
        self.assertIn("entry", str(ctx.exception))


class UnsupportedExitRuleRejectedTests(unittest.TestCase):
    def test_unknown_exit_rule_alongside_supported_ones_is_rejected(self) -> None:
        spec = _spec(_SUPPORTED_BREAKOUT_ENTRY, {**_SUPPORTED_EXIT, "trailing_atr_mult": _v(2.0)}, {})
        with self.assertRaises(UnsupportedStrategyRuleError) as ctx:
            _run(spec)
        self.assertIn("trailing_atr_mult", str(ctx.exception))
        self.assertIn("exit", str(ctx.exception))


class UnsupportedFilterRejectedTests(unittest.TestCase):
    def test_unknown_filter_is_rejected(self) -> None:
        spec = _spec(_SUPPORTED_BREAKOUT_ENTRY, _SUPPORTED_EXIT, {"adx_gte": _v(25)})
        with self.assertRaises(UnsupportedStrategyRuleError) as ctx:
            _run(spec)
        self.assertIn("adx_gte", str(ctx.exception))
        self.assertIn("filter", str(ctx.exception))


class PartialSupportRejectedTests(unittest.TestCase):
    def test_a_partially_supported_spec_never_runs_a_partial_backtest(self) -> None:
        supported = _spec(_SUPPORTED_BREAKOUT_ENTRY, _SUPPORTED_EXIT, {})
        supported_result = _run(supported)
        self.assertGreaterEqual(supported_result.metrics.trade_count, 1)

        # SAME supported breakout rules + one unsupported RSI entry rule.
        # Pre-fix this produced a result byte-for-byte identical to
        # `supported` (RSI silently dropped). It must now be rejected
        # outright - never a partial breakout-only execution.
        partial = _spec({**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30)}, _SUPPORTED_EXIT, {})
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(partial)

    def test_every_violation_is_reported_at_once_not_just_the_first(self) -> None:
        spec = _spec(
            {**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30), "macd_signal_cross": _v(True)},
            {**_SUPPORTED_EXIT, "trailing_atr_mult": _v(2.0)},
            {"adx_gte": _v(25)},
        )
        with self.assertRaises(UnsupportedStrategyRuleError) as ctx:
            _run(spec)
        message = str(ctx.exception)
        for key in ("rsi_below", "macd_signal_cross", "trailing_atr_mult", "adx_gte"):
            self.assertIn(key, message)


class MissingRequiredRuleRejectedTests(unittest.TestCase):
    def test_missing_breakout_lookback_is_an_explicit_domain_error_not_a_bare_keyerror(self) -> None:
        spec = _spec({"close_gt_ma20": _v(True)}, _SUPPORTED_EXIT, {})
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            _run(spec)
        self.assertNotIsInstance(ctx.exception, KeyError)
        self.assertIn("breakout_lookback", str(ctx.exception))

    def test_missing_protective_stop_pct_is_an_explicit_domain_error(self) -> None:
        spec = _spec(_SUPPORTED_BREAKOUT_ENTRY, {"channel_exit_lookback": _v(10)}, {})
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            _run(spec)
        self.assertIn("protective_stop_pct", str(ctx.exception))


class AllExistingFamiliesAcceptedTests(unittest.TestCase):
    def test_every_shipped_family_template_passes_validation(self) -> None:
        self.assertGreaterEqual(len(_TEMPLATE_BY_FAMILY), 16)
        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                spec = build_candidate_spec(family, created_at=NOW)
                # Must not raise, and the capability object must agree.
                validate_strategy_spec_for_rule_based_engine(spec, strategy_family=family)
                self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))

    def test_user_strategy_parser_output_for_every_family_text_passes_validation(self) -> None:
        parser = UserStrategyParser()
        for family, text in _FAMILY_REQUEST_TEXT.items():
            with self.subTest(family=family):
                spec = parser.parse(f"005930 {text}", symbol="005930", created_at=NOW)
                validate_strategy_spec_for_rule_based_engine(spec)
                self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))


class ExistingFamilyBehaviorUnchangedTests(unittest.TestCase):
    def test_validation_gate_changes_nothing_about_a_supported_family_backtest(self) -> None:
        dataset = _dataset()
        assumptions = default_execution_assumptions()
        engine = RuleBasedBacktestEngine()
        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                spec = build_candidate_spec(family, created_at=NOW)
                # With the validation gate bypassed (pre-fix execution path).
                with patch.object(RuleBasedBacktestCapabilities, "validate", lambda *a, **k: None):
                    without_gate = engine.run("wo", spec, dataset, assumptions, generated_at=NOW)
                # With the real validation gate.
                with_gate = engine.run("wo", spec, dataset, assumptions, generated_at=NOW)
                self.assertEqual(without_gate.fingerprint, with_gate.fingerprint)
                self.assertEqual(without_gate.metrics.trade_count, with_gate.metrics.trade_count)
                self.assertEqual(
                    [(t.entry_date, t.exit_date, t.entry_price, t.exit_price, t.exit_reason) for t in without_gate.trades],
                    [(t.entry_date, t.exit_date, t.entry_price, t.exit_price, t.exit_reason) for t in with_gate.trades],
                )


class ValidationOccursBeforeExecutionTests(unittest.TestCase):
    def test_no_trade_simulation_runs_for_an_unsupported_spec(self) -> None:
        spec = _spec({**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30)}, _SUPPORTED_EXIT, {})
        with patch.object(PerformanceMetricsCalculator, "calculate", autospec=True) as metrics_calc:
            with self.assertRaises(UnsupportedStrategySpecError):
                _run(spec)
        metrics_calc.assert_not_called()

    def test_trade_simulation_does_run_for_a_supported_spec(self) -> None:
        spec = _spec(_SUPPORTED_BREAKOUT_ENTRY, _SUPPORTED_EXIT, {})
        with patch.object(PerformanceMetricsCalculator, "calculate", wraps=PerformanceMetricsCalculator().calculate) as metrics_calc:
            _run(spec)
        metrics_calc.assert_called()


class ErrorContainsActionableContextTests(unittest.TestCase):
    def test_error_names_engine_component_key_and_family(self) -> None:
        spec = _spec({**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30)}, _SUPPORTED_EXIT, {})
        with self.assertRaises(UnsupportedStrategyRuleError) as ctx:
            validate_strategy_spec_for_rule_based_engine(spec, strategy_family="rsi_mean_reversion")
        exc = ctx.exception
        message = str(exc)
        self.assertIn(RULE_BASED_ENGINE_NAME, message)
        self.assertIn("rsi_mean_reversion", message)
        self.assertIn("entry", message)
        self.assertIn("rsi_below", message)
        self.assertEqual(exc.engine_name, RULE_BASED_ENGINE_NAME)
        self.assertEqual(exc.strategy_family, "rsi_mean_reversion")
        self.assertIn(("entry", "rsi_below"), exc.unsupported_components)


class CapabilityContractIsExplicitTests(unittest.TestCase):
    def test_capabilities_object_exposes_the_full_grammar(self) -> None:
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertEqual(caps.engine_name, RULE_BASED_ENGINE_NAME)
        # The entry grammar gained the mean-reversion (PR #187) and
        # momentum (this PR) entry triggers and their optional parameters.
        self.assertEqual(
            caps.supported_entry_rules,
            frozenset(
                {
                    "breakout_lookback",
                    "mean_reversion_ma_lookback",
                    "mean_reversion_band_pct",
                    "momentum_roc_lookback",
                    "momentum_min_roc_pct",
                    "close_gt_ma20",
                    "ma20_gt_ma60",
                }
            ),
        )
        self.assertEqual(caps.supported_exit_rules, frozenset({"protective_stop_pct", "channel_exit_lookback"}))
        self.assertEqual(caps.supported_filters, frozenset({"volume_gte_ma20"}))
        # breakout_lookback is no longer individually required - it is one
        # of the entry-trigger GROUP, of which a spec must carry exactly one.
        self.assertEqual(
            caps.entry_trigger_rules,
            frozenset({"breakout_lookback", "mean_reversion_ma_lookback", "momentum_roc_lookback"}),
        )
        self.assertNotIn("breakout_lookback", caps.required_entry_rules)
        self.assertIn("protective_stop_pct", caps.required_exit_rules)

    def test_supports_answers_a_whole_spec_question_not_a_partial_one(self) -> None:
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertTrue(caps.supports(_spec(_SUPPORTED_BREAKOUT_ENTRY, _SUPPORTED_EXIT, {"volume_gte_ma20": _v(True)})))
        self.assertFalse(caps.supports(_spec({**_SUPPORTED_BREAKOUT_ENTRY, "rsi_below": _v(30)}, _SUPPORTED_EXIT, {})))


class RenderCandidateRequestTextFallbackIsDocumentedTests(unittest.TestCase):
    """fix/engine-integrity-known-gap-hardening: for a family with no
    curated _FAMILY_REQUEST_TEXT entry, render_candidate_request_text no
    longer borrows breakout_standard's specific "고가 돌파 ..." wording -
    it names the family honestly. The candidate's real spec_rules still
    fail closed at the engine regardless of the rendered text."""

    def test_fallback_names_the_family_and_engine_still_fails_closed(self) -> None:
        from unittest.mock import patch as _patch

        from gaon.knowledge.strategy_candidate import (
            StrategyFamilyTemplate,
            _TEMPLATE_BY_FAMILY as _TBF,
            new_candidate as _new_candidate,
            render_candidate_request_text,
        )

        gap_family = "engine_capability_test_gap_family"
        gap_template = StrategyFamilyTemplate(
            gap_family, "테스트 전용", {"breakout_lookback": 20, "rsi_below": 30},
            {"protective_stop_pct": -5.0, "channel_exit_lookback": 10}, {},
        )
        with _patch.dict(_TBF, {gap_family: gap_template}):
            candidate = _new_candidate(gap_family, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
            self.assertIn(gap_family, text)
            self.assertNotIn("고가 돌파", text)
            self.assertNotIn("rsi", text.lower())
            # The candidate's real spec_rules still fail closed at the engine.
            spec = _spec(
                {k: _v(v["value"]) for k, v in candidate.spec_rules["entry"].items()},
                {k: _v(v["value"]) for k, v in candidate.spec_rules["exit"].items()},
                {k: _v(v["value"]) for k, v in candidate.spec_rules["filters"].items()},
            )
            self.assertFalse(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
            with self.assertRaises(UnsupportedStrategySpecError):
                _run(spec)


if __name__ == "__main__":
    unittest.main()
