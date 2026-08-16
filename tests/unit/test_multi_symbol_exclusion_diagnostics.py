"""Patch 8.1 - multi-symbol exclusion-reason diagnostics unit tests.

Real production incidents showed multi-symbol research runs collapsing
every exclusion into one generic "데이터 문제로 제외: N종목" line, with no
way to tell a provider/data-acquisition failure (not a strategy problem)
from an actual data-quality block. These tests exercise the classifier and
aggregator directly against synthetic ``SymbolResearchEvidence`` records -
they do not fabricate exclusion categories the pipeline cannot know about.
"""

from __future__ import annotations

import unittest

from gaon.research.multi_symbol import (
    SymbolResearchEvidence,
    _classify_exclusion_reason,
    _exclusion_diagnostics,
)


def _eligible(symbol: str) -> SymbolResearchEvidence:
    return SymbolResearchEvidence(
        evidence_id=f"evidence:{symbol}",
        symbol=symbol,
        eligible=True,
        blocked_reason=None,
        dataset_id=f"dataset:{symbol}",
        dataset_fingerprint="fp",
        quality_status="pass",
        provider="real:yahoo-chart",
        source="real",
        fixture_backed=False,
        rows=250,
        provider_gap_dates=(),
        provider_ohlc_anomaly_dates=(),
        provider_zero_volume_anomaly_dates=(),
        blocking_findings=(),
        metrics={"trade_count": 10},
        backtest_result=None,
        warnings=(),
    )


def _excluded(symbol: str, *, blocked_reason: str | None, blocking_findings: tuple[dict[str, object], ...] = ()) -> SymbolResearchEvidence:
    return SymbolResearchEvidence(
        evidence_id=f"evidence:{symbol}",
        symbol=symbol,
        eligible=False,
        blocked_reason=blocked_reason,
        dataset_id=None,
        dataset_fingerprint=None,
        quality_status="fail",
        provider="real:yahoo-chart",
        source="unknown",
        fixture_backed=False,
        rows=0,
        provider_gap_dates=(),
        provider_ohlc_anomaly_dates=(),
        provider_zero_volume_anomaly_dates=(),
        blocking_findings=blocking_findings,
        metrics={"trade_count": 0},
        backtest_result=None,
        warnings=(),
    )


class ExclusionReasonClassificationTests(unittest.TestCase):
    def test_eligible_symbol_is_not_excluded(self) -> None:
        self.assertEqual(_classify_exclusion_reason(_eligible("005930")), "eligible")

    def test_insufficient_lookback_maps_to_insufficient_bars(self) -> None:
        item = _excluded(
            "005930",
            blocked_reason="blocking_data_quality",
            blocking_findings=({"code": "insufficient_lookback", "severity": "error", "message": "too few bars"},),
        )
        self.assertEqual(_classify_exclusion_reason(item), "insufficient_bars")

    def test_other_quality_finding_maps_to_data_quality_failure(self) -> None:
        item = _excluded(
            "005930",
            blocked_reason="blocking_data_quality",
            blocking_findings=({"code": "invalid_ohlc", "severity": "error", "message": "bad ohlc"},),
        )
        self.assertEqual(_classify_exclusion_reason(item), "data_quality_failure")

    def test_provider_fetch_exception_maps_to_provider_fetch_failure(self) -> None:
        item = _excluded("000660", blocked_reason="RealMarketDataUnavailable: real_data_unavailable: no bars returned")
        self.assertEqual(_classify_exclusion_reason(item), "provider_fetch_failure")

    def test_timeout_exception_maps_to_timeout(self) -> None:
        item = _excluded("005380", blocked_reason="TimeoutError: provider request timed out")
        self.assertEqual(_classify_exclusion_reason(item), "timeout")

    def test_unclassifiable_reason_falls_back_to_other_without_fabricating(self) -> None:
        item = _excluded("035420", blocked_reason="ValueError: something unexpected happened")
        self.assertEqual(_classify_exclusion_reason(item), "other")

    def test_no_reason_at_all_falls_back_to_other(self) -> None:
        item = _excluded("051910", blocked_reason=None)
        self.assertEqual(_classify_exclusion_reason(item), "other")


class ExclusionDiagnosticsAggregationTests(unittest.TestCase):
    def test_aggregates_counts_by_category(self) -> None:
        evidence = (
            _eligible("005930"),
            _eligible("000660"),
            _excluded("005380", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _excluded("035420", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _excluded(
                "051910",
                blocked_reason="blocking_data_quality",
                blocking_findings=({"code": "insufficient_lookback", "severity": "error", "message": "too few bars"},),
            ),
        )
        diagnostics = _exclusion_diagnostics(evidence)
        self.assertEqual(diagnostics["total_excluded"], 3)
        self.assertEqual(diagnostics["by_category"]["provider_fetch_failure"], 2)
        self.assertEqual(diagnostics["by_category"]["insufficient_bars"], 1)
        self.assertEqual(set(diagnostics["excluded_symbols"]), {"005380", "035420", "051910"})

    def test_all_provider_related_exclusions_flagged_as_acquisition_blocker(self) -> None:
        evidence = (
            _excluded("005930", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _excluded("000660", blocked_reason="TimeoutError: timed out"),
        )
        diagnostics = _exclusion_diagnostics(evidence)
        self.assertEqual(diagnostics["provider_related_excluded"], diagnostics["total_excluded"])

    def test_mixed_exclusions_are_not_flagged_as_pure_provider_blocker(self) -> None:
        evidence = (
            _excluded("005930", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _excluded(
                "000660",
                blocked_reason="blocking_data_quality",
                blocking_findings=({"code": "invalid_ohlc", "severity": "error", "message": "bad ohlc"},),
            ),
        )
        diagnostics = _exclusion_diagnostics(evidence)
        self.assertLess(diagnostics["provider_related_excluded"], diagnostics["total_excluded"])

    def test_no_exclusions_yields_empty_breakdown(self) -> None:
        diagnostics = _exclusion_diagnostics((_eligible("005930"), _eligible("000660")))
        self.assertEqual(diagnostics["total_excluded"], 0)
        self.assertEqual(diagnostics["by_category"], {})
        self.assertEqual(diagnostics["provider_related_excluded"], 0)


if __name__ == "__main__":
    unittest.main()
