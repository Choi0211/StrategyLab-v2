"""Phase 1 - keep a REAL multi-symbol dataset context all the way from
``_real_robustness_execution_from_baseline`` into ``_execute_walk_forward``
for the relative-strength family.

Before this change the robustness path always handed ``_execute_walk_forward``
the primary-only dataset, so a relative-strength candidate's walk-forward
folds had no peers and the RS filter fell closed to 0 trades with no
signal that a multi-symbol context was even required.

Now: an RS candidate with real explicit peer datasets gets a combined
primary+peer, timestamp-aligned dataset through walk-forward; without
usable peers the whole robustness result is
``blocked_unsupported_validation_context`` (never promotion-ready, never
fabricated).
"""

from __future__ import annotations

import datetime
import unittest

from gaon.knowledge.autonomous_quant_partner import (
    ResearchBudget,
    _execute_walk_forward,
    _real_robustness_execution_from_baseline,
    _release_baseline_with_real_execution_inputs,
)
from gaon.knowledge.strategy_candidate import build_candidate_spec, spec_rules_to_json
from gaon.research.krx_real_pipeline import default_execution_assumptions
from gaon.research.multi_symbol_validation import (
    MultiSymbolValidationError,
    build_relative_strength_validation_dataset,
)
from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol

NOW = "2026-09-07T00:00:00Z"


_EPOCH = datetime.date(2026, 1, 1)


def _bars(symbol: str, closes: list[float], *, start_day: int = 0) -> list[MarketBar]:
    out = []
    for i, c in enumerate(closes):
        ts = (_EPOCH + datetime.timedelta(days=start_day + i)).isoformat()
        out.append(MarketBar(ts, symbol, c * 0.997, c, c * 0.985, c, 1_000_000 + i, int(c * 1_000)))
    return out


def _dataset(series: dict[str, list[float]], *, dataset_id: str = "dataset:rs-wiring") -> MarketDataset:
    bars: list[MarketBar] = []
    for sym, closes in series.items():
        bars.extend(_bars(sym, closes))
    ts = sorted({b.timestamp for b in bars})
    meta = MarketDataMetadata("real:test", "KOSPI", "daily", ts[0], ts[-1], True, NOW, False)
    syms = tuple(MarketSymbol(s, s, "KOSPI") for s in series)
    return MarketDataset(dataset_id, syms, tuple(bars), meta)


def _wave(n: int, base: float = 100.0) -> list[float]:
    return [base + (i % 25) * 1.6 - (i % 7) * 0.9 + i * 0.05 for i in range(n)]


def _rs_candidate_strategy_json(symbol: str = "005930") -> dict[str, object]:
    spec = build_candidate_spec("breakout_relative_strength", created_at=NOW)
    payload = spec_rules_to_json(spec)
    payload["symbol"] = symbol
    payload["spec_id"] = "canonical-strategy:rs-test"
    return payload


class BuildRelativeStrengthValidationDatasetTests(unittest.TestCase):
    def test_combines_primary_and_real_peers_on_one_timestamp_grid(self) -> None:
        primary = _dataset({"005930": _wave(160)}, dataset_id="dataset:primary")
        peers = [
            _dataset({"000660": _wave(160, base=90)}, dataset_id="dataset:peer1"),
            _dataset({"005380": _wave(160, base=70)}, dataset_id="dataset:peer2"),
        ]
        combined = build_relative_strength_validation_dataset(primary, peers, primary_symbol="005930")
        by_symbol = {}
        for b in combined.bars:
            by_symbol.setdefault(b.symbol, set()).add(b.timestamp)
        self.assertEqual(set(by_symbol), {"005930", "000660", "005380"})
        # every symbol on the exact same closed-bar timestamps
        self.assertEqual(by_symbol["005930"], by_symbol["000660"])
        self.assertEqual(by_symbol["005930"], by_symbol["005380"])

    def test_zero_peers_fails_closed(self) -> None:
        primary = _dataset({"005930": _wave(160)})
        with self.assertRaises(MultiSymbolValidationError):
            build_relative_strength_validation_dataset(primary, [], primary_symbol="005930")

    def test_primary_missing_fails_closed(self) -> None:
        primary = _dataset({"005930": _wave(160)})
        peers = [_dataset({"000660": _wave(160)})]
        with self.assertRaises(MultiSymbolValidationError):
            build_relative_strength_validation_dataset(primary, peers, primary_symbol="999999")

    def test_peer_timeline_too_short_fails_closed(self) -> None:
        primary = _dataset({"005930": _wave(160)})
        peers = [_dataset({"000660": _wave(40)})]  # only 40 shared bars
        with self.assertRaises(MultiSymbolValidationError):
            build_relative_strength_validation_dataset(primary, peers, primary_symbol="005930")

    def test_peer_not_covering_the_primary_timeline_fails_closed(self) -> None:
        primary = _dataset({"005930": _wave(160)})
        # peer shifted forward so it never overlaps the primary's early bars
        shifted = _dataset({"000660": _wave(160)}, dataset_id="dataset:shift")
        shifted = MarketDataset(
            shifted.dataset_id,
            shifted.symbols,
            tuple(MarketBar(f"2027-{i%12+1:02d}-15", b.symbol, b.open, b.high, b.low, b.close, b.volume, b.trading_value)
                  for i, b in enumerate(shifted.bars)),
            shifted.metadata,
        )
        with self.assertRaises(MultiSymbolValidationError):
            build_relative_strength_validation_dataset(primary, [shifted], primary_symbol="005930")

    def test_no_fabricated_peer_or_benchmark_when_a_peer_has_gaps(self) -> None:
        primary = _dataset({"005930": _wave(160)})
        full_peer = _dataset({"000660": _wave(160)})
        gappy = MarketDataset(
            "dataset:gappy",
            (MarketSymbol("005380", "005380", "KOSPI"),),
            tuple(b for i, b in enumerate(_bars("005380", _wave(160))) if i % 2 == 0),  # half the bars
            full_peer.metadata,
        )
        with self.assertRaises(MultiSymbolValidationError):
            build_relative_strength_validation_dataset(primary, [full_peer, gappy], primary_symbol="005930")


class ExecuteWalkForwardMultiSymbolBranchTests(unittest.TestCase):
    def _combined(self) -> MarketDataset:
        primary = _dataset({"005930": _wave(420)}, dataset_id="dataset:p")
        peers = [
            _dataset({"000660": _wave(420, base=88)}, dataset_id="dataset:q"),
            _dataset({"005380": _wave(420, base=64)}, dataset_id="dataset:r"),
        ]
        return build_relative_strength_validation_dataset(primary, peers, primary_symbol="005930")

    def test_folds_run_on_the_combined_dataset_and_keep_the_peers(self) -> None:
        combined = self._combined()
        spec = build_candidate_spec("breakout_relative_strength", created_at=NOW)
        result = _execute_walk_forward(
            "wf-multi", combined, spec, spec, default_execution_assumptions(), ResearchBudget(), primary_symbol="005930"
        )
        self.assertTrue(result.get("executed"))
        self.assertEqual(result.get("lineage"), "actual_backtest")
        self.assertFalse(result.get("fabricated_metrics"))
        self.assertGreaterEqual(len(result.get("folds") or []), 1)
        # the split boundary is a single date shared by every symbol
        for fold in result["folds"]:
            self.assertLessEqual(str(fold["train_end"]), str(fold["evaluation_start"]))

    def test_single_symbol_path_is_unchanged_by_the_new_kwarg(self) -> None:
        single = _dataset({"005930": _wave(420)}, dataset_id="dataset:solo")
        spec = build_candidate_spec("breakout_standard", created_at=NOW)
        a = _execute_walk_forward("wf-a", single, spec, spec, default_execution_assumptions(), ResearchBudget())
        b = _execute_walk_forward(
            "wf-a", single, spec, spec, default_execution_assumptions(), ResearchBudget(), primary_symbol="005930"
        )
        self.assertEqual(a["fold_count"], b["fold_count"])
        self.assertEqual(a["status"], b["status"])
        self.assertEqual(
            [f["candidate_strategy_fingerprint"] for f in a["folds"]],
            [f["candidate_strategy_fingerprint"] for f in b["folds"]],
        )


class RealRobustnessExecutionWiringTests(unittest.TestCase):
    def _rs_baseline(self) -> dict[str, object]:
        baseline = _release_baseline_with_real_execution_inputs()
        strat = _rs_candidate_strategy_json("005930")
        baseline["candidates"] = [
            {
                "candidate_id": "candidate:relative_strength",
                "strategy": strat,
                "backtest_result": {
                    "result_id": "backtest:candidate:rs",
                    "source": "real",
                    "strategy": strat,
                    "metrics": {"trade_count": 12, "total_return": 0.05, "mdd": 0.06},
                },
            }
        ]
        return baseline

    def test_rs_candidate_with_real_peers_gets_a_multi_symbol_walk_forward(self) -> None:
        baseline = self._rs_baseline()
        result = _real_robustness_execution_from_baseline(
            "상대강도 전략 연구", symbol="005930", baseline=baseline, budget=ResearchBudget(), connection=None
        )
        ctx = result.get("relative_strength_validation_context")
        self.assertIsInstance(ctx, dict)
        self.assertEqual(ctx.get("status"), "real_multi_symbol")
        self.assertEqual(ctx.get("primary"), "005930")
        self.assertGreaterEqual(len(ctx.get("peers") or []), 1)
        self.assertNotIn("005930", ctx.get("peers") or [])
        self.assertTrue(result.get("walk_forward", {}).get("executed"))

    def test_rs_candidate_without_usable_peers_fails_closed(self) -> None:
        baseline = self._rs_baseline()
        baseline.pop("peer_datasets", None)  # connection=None -> _peer_dataset raises
        result = _real_robustness_execution_from_baseline(
            "상대강도 전략 연구", symbol="005930", baseline=baseline, budget=ResearchBudget(), connection=None
        )
        self.assertEqual(result.get("execution_state"), "blocked_unsupported_validation_context")
        self.assertTrue(any("UNSUPPORTED_VALIDATION_CONTEXT" in str(b) for b in result.get("blockers") or []))
        self.assertIs(result.get("fabricated_metrics"), False)

    def test_non_rs_candidate_path_is_untouched(self) -> None:
        baseline = _release_baseline_with_real_execution_inputs()  # breakout candidate, no RS filter
        result = _real_robustness_execution_from_baseline(
            "돌파 전략 연구", symbol="005930", baseline=baseline, budget=ResearchBudget(), connection=None
        )
        self.assertNotIn("relative_strength_validation_context", result)
        self.assertEqual(result.get("execution_state"), "executed")
        self.assertTrue(result.get("walk_forward", {}).get("executed"))


if __name__ == "__main__":
    unittest.main()
