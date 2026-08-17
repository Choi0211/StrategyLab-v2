"""Patch 8.4 - KR multi-symbol data acquisition & quality diagnostics.

Real production incident this patch investigates and fixes: a market-wide
strategy candidate research cycle against real KOSPI/KOSDAQ symbols
(real KIS-master universe + real Yahoo Chart data, confirmed via a live
network investigation during this patch, not guessed) excluded 13-15 of 15
attempted symbols as a generic "data_quality_failure" on almost every
cycle.

Root cause (confirmed against REAL data, not fixtures): DataQualityEngine
correctly labels an individual zero-volume bar severity="warning" - a
real, common KRX market artifact (thin trading, preferred shares,
holiday-adjacent sessions), not a data-integrity error. But
krx_real_pipeline._blocking_quality_findings treats any finding whose CODE
is not in a narrow allowlist as blocking regardless of severity, and the
raw "zero_volume" code (used whenever GlobalMarketDataProvider.
validate_dataset validates a dataset, which is what market-wide research
actually uses) is not in that allowlist - so a single isolated zero-volume
day anywhere in a 5-year window silently excluded an otherwise healthy,
actively-traded real stock.

A live investigation against 15 real KOSPI/KOSDAQ symbols found a clean,
evidence-backed split: 12 of 15 had isolated zero-volume days (0.6%-6.6%
of bars, longest consecutive run <=16 bars, none reaching the dataset's
last bar) - a normal artifact. Exactly 2 of 15 had a SUSTAINED run of
zero-volume bars reaching the dataset's last bar (15 and 473 consecutive
bars) - real evidence the security stopped trading.

These tests exercise the resulting classifier/funnel refinement against
synthetic data shaped EXACTLY like that real evidence (isolated vs.
tail-stale runs), never lowering the underlying quality bar (every
error-severity finding still blocks exactly as before).
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.krx_real_pipeline import RealMarketDataUnavailable
from gaon.research.real_research import DataQualityEngine, MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol
from gaon.research.multi_symbol import (
    AutonomousMultiSymbolResearchOrchestrator,
    SymbolResearchEvidence,
    _acquisition_funnel,
    _classify_exclusion_reason,
    _exclusion_diagnostics,
    _multi_symbol_blocking_findings,
    _tail_stale_zero_volume_dates,
)
from gaon.research.global_market import MarketScope, select_bounded_universe
from gaon.runtime.migrations import migrate

REQUEST = "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산"


def _dataset_with_bars(symbol: str, bars: tuple[MarketBar, ...]) -> MarketDataset:
    metadata = MarketDataMetadata("real:test", "KOSPI", "daily", bars[0].timestamp, bars[-1].timestamp, True, "2026-08-17T00:00:00Z", False)
    return MarketDataset(f"dataset:{symbol}", (MarketSymbol(symbol, symbol, "KOSPI"),), bars, metadata)


def _daily_bars(symbol: str, count: int, *, zero_volume_indices: frozenset[int] = frozenset()) -> tuple[MarketBar, ...]:
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    bars = []
    for index in range(count):
        day = (start + timedelta(days=index)).isoformat()
        close = 100.0 + index * 0.1
        volume = 0 if index in zero_volume_indices else 1_000_000
        bars.append(MarketBar(day, symbol, close, close + 1.0, close - 1.0, close, volume, int(close * volume)))
    return tuple(bars)


class TailStaleZeroVolumeDetectionTests(unittest.TestCase):
    """Real-evidence-shaped isolated vs. tail-stale-run distinction."""

    def test_isolated_scattered_zero_volume_bars_are_not_a_tail_stale_run(self) -> None:
        # Shaped like real symbol 192410: scattered zero-volume days, none
        # reaching the last bar.
        bars = _daily_bars("192410", 200, zero_volume_indices=frozenset({10, 40, 70, 100, 130}))
        dataset = _dataset_with_bars("192410", bars)
        self.assertEqual(_tail_stale_zero_volume_dates(dataset), frozenset())

    def test_short_run_below_threshold_at_the_tail_is_not_stale(self) -> None:
        bars = _daily_bars("003540", 200, zero_volume_indices=frozenset({197, 198, 199}))  # 3 consecutive, ends at last bar
        dataset = _dataset_with_bars("003540", bars)
        self.assertEqual(_tail_stale_zero_volume_dates(dataset), frozenset())

    def test_long_run_in_the_middle_of_history_is_not_a_tail_stale_run(self) -> None:
        # A real halt that later resumed trading is still real historical
        # data, not evidence the symbol is stale AS OF the requested end
        # date.
        bars = _daily_bars("113810", 200, zero_volume_indices=frozenset(range(50, 70)))
        dataset = _dataset_with_bars("113810", bars)
        self.assertEqual(_tail_stale_zero_volume_dates(dataset), frozenset())

    def test_sustained_run_reaching_the_last_bar_is_a_tail_stale_run(self) -> None:
        # Shaped like real symbol 082660: a long run of zero-volume bars
        # reaching the dataset's last (most recently requested) bar.
        bars = _daily_bars("082660", 200, zero_volume_indices=frozenset(range(150, 200)))
        dataset = _dataset_with_bars("082660", bars)
        tail_dates = _tail_stale_zero_volume_dates(dataset)
        self.assertEqual(len(tail_dates), 50)
        self.assertIn(bars[-1].timestamp, tail_dates)

    def test_no_zero_volume_bars_at_all(self) -> None:
        bars = _daily_bars("373110", 100)
        dataset = _dataset_with_bars("373110", bars)
        self.assertEqual(_tail_stale_zero_volume_dates(dataset), frozenset())


class MultiSymbolBlockingFindingsTests(unittest.TestCase):
    def test_isolated_zero_volume_warning_is_not_blocking(self) -> None:
        bars = _daily_bars("122350", 200, zero_volume_indices=frozenset({20, 80}))
        dataset = _dataset_with_bars("122350", bars)
        quality = DataQualityEngine().validate(dataset, min_bars=60)
        self.assertTrue(any(finding.code == "zero_volume" for finding in quality.findings))
        blocking = _multi_symbol_blocking_findings(quality, dataset)
        self.assertEqual(blocking, ())

    def test_tail_stale_run_zero_volume_warning_still_blocks(self) -> None:
        bars = _daily_bars("082660", 200, zero_volume_indices=frozenset(range(150, 200)))
        dataset = _dataset_with_bars("082660", bars)
        quality = DataQualityEngine().validate(dataset, min_bars=60)
        blocking = _multi_symbol_blocking_findings(quality, dataset)
        self.assertTrue(blocking)
        self.assertTrue(all(finding.code == "zero_volume" for finding in blocking))

    def test_error_severity_findings_are_never_filtered(self) -> None:
        # A genuine data-integrity error (duplicate bars) must still block
        # regardless of any zero-volume handling - the quality bar for
        # real errors is completely untouched by this patch.
        bars = _daily_bars("005930", 100)
        duplicated = bars + (bars[-1],)
        dataset = _dataset_with_bars("005930", duplicated)
        quality = DataQualityEngine().validate(dataset, min_bars=60)
        blocking = _multi_symbol_blocking_findings(quality, dataset)
        self.assertTrue(any(finding.code == "duplicate_bars" for finding in blocking))


class ZeroVolumeExclusionClassificationTests(unittest.TestCase):
    def test_tail_stale_zero_volume_classifies_as_stale_data(self) -> None:
        item = SymbolResearchEvidence(
            evidence_id="evidence:082660", symbol="082660", eligible=False, blocked_reason="blocking_data_quality",
            dataset_id=None, dataset_fingerprint=None, quality_status="pass_with_warnings", provider="real:kis-master+yahoo-chart",
            source="unknown", fixture_backed=False, rows=1218,
            provider_gap_dates=(), provider_ohlc_anomaly_dates=(), provider_zero_volume_anomaly_dates=(),
            blocking_findings=({"code": "zero_volume", "severity": "warning", "message": "zero volume bar requires review: symbol=082660 date=2026-07-24"},),
            metrics={"trade_count": 0}, backtest_result=None, warnings=(),
        )
        self.assertEqual(_classify_exclusion_reason(item), "stale_data")


class AcquisitionFunnelTests(unittest.TestCase):
    def _eligible(self, symbol: str, *, rows: int = 1200) -> SymbolResearchEvidence:
        return SymbolResearchEvidence(
            evidence_id=f"evidence:{symbol}", symbol=symbol, eligible=True, blocked_reason=None,
            dataset_id=f"dataset:{symbol}", dataset_fingerprint="fp", quality_status="pass_with_warnings",
            provider="real:kis-master+yahoo-chart", source="real", fixture_backed=False, rows=rows,
            provider_gap_dates=(), provider_ohlc_anomaly_dates=(), provider_zero_volume_anomaly_dates=(),
            blocking_findings=(), metrics={"trade_count": 10}, backtest_result="stand-in-not-none", warnings=(),
        )

    def _excluded(self, symbol: str, *, category_findings: tuple[dict[str, object], ...], rows: int = 0) -> SymbolResearchEvidence:
        return SymbolResearchEvidence(
            evidence_id=f"evidence:{symbol}", symbol=symbol, eligible=False, blocked_reason="blocking_data_quality" if rows else "fetch_failed",
            dataset_id=None, dataset_fingerprint=None, quality_status="fail", provider="real:kis-master+yahoo-chart",
            source="unknown", fixture_backed=False, rows=rows,
            provider_gap_dates=(), provider_ohlc_anomaly_dates=(), provider_zero_volume_anomaly_dates=(),
            blocking_findings=category_findings, metrics={"trade_count": 0}, backtest_result=None, warnings=(),
        )

    def test_funnel_counts_are_derived_from_real_evidence_not_fabricated(self) -> None:
        evidence = (
            self._eligible("009200"),
            self._eligible("037950"),
            self._excluded("082660", category_findings=({"code": "zero_volume", "severity": "warning", "message": "..."},), rows=1218),
            self._excluded("999999", category_findings=({"code": "provider_failure", "severity": "error", "message": "RealMarketDataUnavailable: no bars"},), rows=0),
        )
        funnel = _acquisition_funnel(evidence)
        self.assertEqual(funnel["selected"], 4)
        self.assertEqual(funnel["provider_fetch_succeeded"], 3)  # only the fetch failure has rows=0
        self.assertEqual(funnel["quality_checked"], 3)
        self.assertEqual(funnel["quality_passed"], 2)
        self.assertEqual(funnel["research_eligible"], 2)
        self.assertEqual(funnel["strategy_tested"], 2)


class AvoidSymbolsBoundedSamplingTests(unittest.TestCase):
    def test_previously_excluded_symbols_are_skipped_when_possible(self) -> None:
        candidates = (
            MarketSymbol("005930", "005930", "KR", "KOSPI"),
            MarketSymbol("000660", "000660", "KR", "KOSPI"),
            MarketSymbol("005380", "005380", "KR", "KOSPI"),
        )
        scope = MarketScope("KR", ("KOSPI",), ("KRW",), ("Asia/Seoul",), True, "KOSPI 전체")
        selection = select_bounded_universe(
            candidates, scope, requested_size=2, seed="seed", source="test", avoid_symbols=frozenset({"005930"})
        )
        self.assertNotIn("005930", selection.symbols)

    def test_avoid_symbols_never_leaves_an_empty_universe(self) -> None:
        # Bounded, safe fallback: if every candidate happens to be on the
        # avoid list, sampling still proceeds from the full pool rather
        # than raising - never an unbounded/blocking failure mode.
        candidates = (MarketSymbol("005930", "005930", "KR", "KOSPI"),)
        scope = MarketScope("KR", ("KOSPI",), ("KRW",), ("Asia/Seoul",), True, "KOSPI 전체")
        selection = select_bounded_universe(
            candidates, scope, requested_size=1, seed="seed", source="test", avoid_symbols=frozenset({"005930"})
        )
        self.assertEqual(selection.symbols, ("005930",))


class _ShapedRealEvidenceProvider:
    """Wraps the deterministic ``_ReleaseCheckProvider`` and injects
    zero-volume patterns matching the REAL production evidence this patch
    investigated, plus optional provider fetch failures - so the following
    tests exercise the REAL orchestrator end-to-end (not a hand-built
    SymbolResearchEvidence fixture) against data shaped exactly like a real
    KOSPI/KOSDAQ acquisition cycle."""

    source = "real:synthetic-release-check"

    def __init__(self, *, isolated_zero_volume: frozenset[str] = frozenset(), tail_stale: frozenset[str] = frozenset(), fetch_failing: frozenset[str] = frozenset()) -> None:
        self._delegate = _ReleaseCheckProvider()
        self._isolated = isolated_zero_volume
        self._tail_stale = tail_stale
        self._fetch_failing = fetch_failing

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        upper = symbol.upper()
        if upper in self._fetch_failing:
            raise RealMarketDataUnavailable(f"real_data_unavailable: no bars returned for {symbol}")
        dataset = self._delegate.fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)
        bars = list(dataset.bars)
        if upper in self._isolated:
            for index in (5, 40, 90):
                if index < len(bars):
                    bar = bars[index]
                    bars[index] = MarketBar(bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, 0, 0)
        if upper in self._tail_stale:
            for index in range(max(0, len(bars) - 10), len(bars)):
                bar = bars[index]
                bars[index] = MarketBar(bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, 0, 0)
        return MarketDataset(dataset.dataset_id, dataset.symbols, tuple(bars), dataset.metadata)


class RealProductionFailureShapeRegressionTests(unittest.TestCase):
    """Reproduces the exact real production failure shapes from the
    incident report and proves the fix (not the classifier alone - the
    real orchestrator end-to-end)."""

    def _run(self, provider: _ShapedRealEvidenceProvider, symbols: tuple[str, ...]) -> dict[str, object]:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            orchestrator = AutonomousMultiSymbolResearchOrchestrator(connection, provider, _ReleaseCheckBacktestRunner())
            run = orchestrator.run(REQUEST, run_id="unit:patch84", symbols=symbols, generated_at="2026-08-17T00:00:00Z", start_date="2021-07-25", end_date="2026-07-24")
            return run.to_json()
        finally:
            connection.close()

    def test_case_a_mixed_isolated_stale_and_provider_failure(self) -> None:
        symbols = tuple(f"{100000 + i:06d}" for i in range(15))
        # 13 isolated (must now be eligible), 1 tail-stale (must exclude as
        # stale_data), 1 provider fetch failure (must exclude as
        # provider_fetch_failure, never data_quality_failure).
        provider = _ShapedRealEvidenceProvider(
            isolated_zero_volume=frozenset(symbols[:13]),
            tail_stale=frozenset({symbols[13]}),
            fetch_failing=frozenset({symbols[14]}),
        )
        payload = self._run(provider, symbols)
        diagnostics = payload["exclusion_diagnostics"]
        self.assertEqual(diagnostics["total_excluded"], 2, diagnostics)
        self.assertEqual(diagnostics["by_category"].get("stale_data"), 1)
        self.assertEqual(diagnostics["by_category"].get("provider_fetch_failure"), 1)
        self.assertNotIn("data_quality_failure", diagnostics["by_category"])
        funnel = payload["acquisition_funnel"]
        self.assertEqual(funnel["selected"], 15)
        self.assertEqual(funnel["research_eligible"], 13)

    def test_case_b_all_isolated_zero_volume_no_longer_excludes_every_symbol(self) -> None:
        # The exact reported "apparent 15/15 data_quality_failure" shape -
        # every symbol has ONLY isolated (non-tail-stale) zero-volume days.
        symbols = tuple(f"{200000 + i:06d}" for i in range(15))
        provider = _ShapedRealEvidenceProvider(isolated_zero_volume=frozenset(symbols))
        payload = self._run(provider, symbols)
        diagnostics = payload["exclusion_diagnostics"]
        self.assertEqual(diagnostics["total_excluded"], 0, diagnostics)
        funnel = payload["acquisition_funnel"]
        self.assertEqual(funnel["research_eligible"], 15)

    def test_provider_outage_regression_never_classified_as_data_quality_failure(self) -> None:
        symbols = ("300001", "300002")
        provider = _ShapedRealEvidenceProvider(fetch_failing=frozenset(symbols))
        payload = self._run(provider, symbols)
        diagnostics = payload["exclusion_diagnostics"]
        self.assertEqual(diagnostics["by_category"].get("data_quality_failure", 0), 0)
        self.assertEqual(diagnostics["by_category"].get("stale_data", 0), 0)
        self.assertEqual(diagnostics["by_category"].get("provider_fetch_failure"), 2)


class DataAcquisitionReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_deterministically(self) -> None:
        from gaon.research.multi_symbol import production_kr_multi_symbol_data_acquisition_release_check

        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            result = production_kr_multi_symbol_data_acquisition_release_check(connection)
        finally:
            connection.close()
        self.assertTrue(result["acquisition_funnel_structured"])
        self.assertTrue(result["exclusion_reason_evidence_backed"])
        self.assertTrue(result["provider_failure_not_misclassified_as_data_quality_failure"])
        self.assertTrue(result["timeout_not_misclassified_as_data_quality_failure"])
        self.assertTrue(result["insufficient_history_not_misclassified_as_provider_failure"])
        self.assertTrue(result["research_eligible_only_passed_to_strategy_validation"])
        self.assertTrue(result["bounded_retry_cap_preserved"])
        self.assertTrue(result["mission_scope_unchanged"])
        self.assertTrue(result["candidate_fingerprint_unchanged"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])
        self.assertFalse(result["champion_promoted"])
        self.assertFalse(result["approval_bypassed"])
        self.assertEqual(result["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
