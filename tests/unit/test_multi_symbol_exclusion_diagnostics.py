"""Patch 8.1 - multi-symbol exclusion-reason diagnostics unit tests.

Real production incidents showed multi-symbol research runs collapsing
every exclusion into one generic "데이터 문제로 제외: N종목" line, with no
way to tell a provider/data-acquisition failure (not a strategy problem)
from an actual data-quality block. These tests exercise the classifier and
aggregator directly against synthetic ``SymbolResearchEvidence`` records -
they do not fabricate exclusion categories the pipeline cannot know about.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.krx_real_pipeline import RealMarketDataUnavailable
from gaon.research.multi_symbol import (
    AutonomousMultiSymbolResearchOrchestrator,
    SymbolResearchEvidence,
    _classify_exclusion_reason,
    _exclusion_diagnostics,
)
from gaon.runtime.migrations import migrate

REQUEST = "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산"


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


def _acquisition_failure(symbol: str, *, blocked_reason: str) -> SymbolResearchEvidence:
    """Builds evidence in the EXACT shape
    ``AutonomousMultiSymbolResearchOrchestrator._symbol_evidence``'s own
    ``except Exception as exc:`` handler produces: ``blocked_reason`` set to
    the exception class/message AND ``blocking_findings`` carrying the
    ``provider_failure`` sentinel code - not the empty ``blocking_findings``
    shape a hand-written data-quality-only fixture would use."""
    return _excluded(
        symbol,
        blocked_reason=blocked_reason,
        blocking_findings=({"code": "provider_failure", "severity": "error", "message": blocked_reason},),
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
        # Production shape: blocking_findings carries the orchestrator's own
        # "provider_failure" sentinel alongside blocked_reason - not empty
        # blocking_findings. H1 regression: this must NOT fall through to
        # "data_quality_failure".
        item = _acquisition_failure("000660", blocked_reason="RealMarketDataUnavailable: real_data_unavailable: no bars returned")
        self.assertEqual(_classify_exclusion_reason(item), "provider_fetch_failure")

    def test_timeout_exception_maps_to_timeout(self) -> None:
        item = _acquisition_failure("005380", blocked_reason="TimeoutError: provider request timed out")
        self.assertEqual(_classify_exclusion_reason(item), "timeout")

    def test_kis_master_mismatch_exception_maps_to_kis_master_mismatch(self) -> None:
        item = _acquisition_failure("005930", blocked_reason="ValueError: KIS master symbol mismatch for 005930")
        self.assertEqual(_classify_exclusion_reason(item), "kis_master_mismatch")

    def test_symbol_resolution_exception_maps_to_symbol_resolution_failure(self) -> None:
        item = _acquisition_failure("999999", blocked_reason="ValueError: symbol not found in KRX master")
        self.assertEqual(_classify_exclusion_reason(item), "symbol_resolution_failure")

    def test_unsupported_security_exception_maps_to_unsupported_security(self) -> None:
        item = _acquisition_failure("999998", blocked_reason="RealMarketDataUnavailable: real_data_unavailable: unsupported security type")
        self.assertEqual(_classify_exclusion_reason(item), "unsupported_security")

    def test_unclassifiable_reason_falls_back_to_other_without_fabricating(self) -> None:
        item = _acquisition_failure("035420", blocked_reason="ValueError: something unexpected happened")
        self.assertEqual(_classify_exclusion_reason(item), "other")

    def test_no_reason_at_all_falls_back_to_other(self) -> None:
        item = _excluded("051910", blocked_reason=None)
        self.assertEqual(_classify_exclusion_reason(item), "other")

    def test_provider_failure_sentinel_alone_never_becomes_data_quality_failure(self) -> None:
        """H1 regression: the orchestrator's own generic 'provider_failure'
        finding code must never, by itself, be classified as a data-quality
        problem - even when the message gives no further detail."""
        item = _acquisition_failure("123456", blocked_reason="RuntimeError: boom")
        self.assertNotEqual(_classify_exclusion_reason(item), "data_quality_failure")


class ExclusionDiagnosticsAggregationTests(unittest.TestCase):
    def test_aggregates_counts_by_category(self) -> None:
        evidence = (
            _eligible("005930"),
            _eligible("000660"),
            _acquisition_failure("005380", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _acquisition_failure("035420", blocked_reason="RealMarketDataUnavailable: no bars returned"),
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
        # H1 regression: production-shaped provider failures (blocking_findings
        # carries the sentinel code, not empty) must still be recognized as
        # 100% provider-related.
        evidence = (
            _acquisition_failure("005930", blocked_reason="RealMarketDataUnavailable: no bars returned"),
            _acquisition_failure("000660", blocked_reason="TimeoutError: timed out"),
        )
        diagnostics = _exclusion_diagnostics(evidence)
        self.assertEqual(diagnostics["provider_related_excluded"], diagnostics["total_excluded"])
        self.assertEqual(diagnostics["total_excluded"], 2)
        from gaon.knowledge.research_mission import is_provider_acquisition_blocker

        self.assertTrue(is_provider_acquisition_blocker(diagnostics))

    def test_mixed_exclusions_are_not_flagged_as_pure_provider_blocker(self) -> None:
        evidence = (
            _acquisition_failure("005930", blocked_reason="RealMarketDataUnavailable: no bars returned"),
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


class _PartiallyFailingProvider:
    """A market-data provider that raises the SAME
    ``RealMarketDataUnavailable`` shape a real provider outage raises for a
    chosen subset of symbols, and otherwise delegates to the existing
    deterministic ``_ReleaseCheckProvider``. Used to prove end-to-end,
    through the real ``AutonomousMultiSymbolResearchOrchestrator``, that a
    genuine acquisition failure is never reported as a data-quality problem -
    not just that the classifier function alone handles a hand-built shape.
    """

    source = "real:synthetic-release-check"

    def __init__(self, failing_symbols: frozenset[str]) -> None:
        self._failing_symbols = failing_symbols
        self._delegate = _ReleaseCheckProvider()

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily"):
        if symbol.upper() in self._failing_symbols:
            raise RealMarketDataUnavailable(f"real_data_unavailable: no bars returned for {symbol}")
        return self._delegate.fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)


class RealOrchestratorAcquisitionFailureRegressionTests(unittest.TestCase):
    """H1 regression: runs the REAL orchestrator (not a hand-built
    SymbolResearchEvidence fixture) against a provider that fails exactly
    the way a real KIS/Yahoo outage does, and checks the resulting
    exclusion_diagnostics on the actual persisted run."""

    def test_real_provider_outage_is_never_reported_as_data_quality_failure(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            failing = frozenset({"000660", "005380"})
            provider = _PartiallyFailingProvider(failing)
            orchestrator = AutonomousMultiSymbolResearchOrchestrator(connection, provider, _ReleaseCheckBacktestRunner())
            run = orchestrator.run(
                REQUEST,
                run_id="unit:acquisition-failure",
                symbols=("005930", "000660", "005380", "035420"),
                generated_at="2026-08-17T00:00:00Z",
            )
            diagnostics = run.to_json()["exclusion_diagnostics"]
            self.assertEqual(diagnostics["total_excluded"], 2)
            self.assertEqual(diagnostics["by_category"].get("data_quality_failure", 0), 0)
            self.assertEqual(diagnostics["by_category"].get("provider_fetch_failure"), 2)
            self.assertEqual(diagnostics["provider_related_excluded"], diagnostics["total_excluded"])

            from gaon.knowledge.research_mission import is_provider_acquisition_blocker

            self.assertTrue(is_provider_acquisition_blocker(diagnostics))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
