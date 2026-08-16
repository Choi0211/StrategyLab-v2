import sqlite3
import unittest

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.krx_universe import (
    KRXUniverseFixtureProvider,
    KRXUniverseRequest,
    KRXUniverseSelector,
    krx_universe_release_check,
)
from gaon.research.multi_symbol import AutonomousMultiSymbolResearchOrchestrator, DEFAULT_REQUEST_TEXT, KRXResearchUniverseResolver
from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol
from gaon.research.krx_real_pipeline import RealMarketDataUnavailable
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import migrate


NOW = "2026-07-30T00:00:00Z"


class KRXUniverseSelectionTests(unittest.TestCase):
    def test_trading_value_descending_and_symbol_tie_break(self) -> None:
        result = KRXUniverseSelector(_TieProvider()).select(KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 3), generated_at=NOW)

        self.assertEqual(result.symbols, ("000660", "005380", "005930"))
        self.assertEqual([entry.rank for entry in result.ranked_entries], [1, 2, 3])

    def test_invalid_request_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            KRXUniverseRequest("NYSE", "2026-07-30", "trading_value", 3)
        with self.assertRaises(ValueError):
            KRXUniverseRequest("ALL", "2026/07/30", "trading_value", 3)
        with self.assertRaises(ValueError):
            KRXUniverseRequest("ALL", "2026-07-30", "volume", 3)
        with self.assertRaises(ValueError):
            KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 0)

    def test_non_trading_selection_date_fails_closed(self) -> None:
        with self.assertRaises(RealMarketDataUnavailable):
            KRXUniverseSelector().select(KRXUniverseRequest("ALL", "2026-07-26", "trading_value", 3), generated_at=NOW)

    def test_zero_volume_zero_trading_value_duplicates_and_exclusions(self) -> None:
        result = KRXUniverseSelector(_DirtyProvider()).select(
            KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 3, exclusions=("005380.KS",)),
            generated_at=NOW,
        )

        self.assertEqual(result.symbols, ("005930",))
        reasons = {item.symbol: item.reason for item in result.exclusions}
        self.assertEqual(reasons["000660"], "zero_volume")
        self.assertEqual(reasons["051910"], "zero_trading_value")
        self.assertEqual(reasons["005380"], "user_excluded")
        self.assertTrue(result.warnings)

    def test_canonical_symbol_and_deterministic_json(self) -> None:
        request = KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 5, exclusions=("005930.KS", "KQ:091990"))

        self.assertEqual(request.exclusions, ("005930", "091990"))
        first = KRXUniverseSelector(KRXUniverseFixtureProvider()).select(request, generated_at=NOW).to_json()
        second = KRXUniverseSelector(KRXUniverseFixtureProvider()).select(request, generated_at=NOW).to_json()
        self.assertEqual(first, second)
        self.assertTrue(first["fixture_backed"])

    def test_provider_failure_fails_closed(self) -> None:
        with self.assertRaises(RealMarketDataUnavailable):
            KRXUniverseSelector(_FailingProvider()).select(KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 3), generated_at=NOW)

    def test_release_check_contract_and_safe_tool(self) -> None:
        payload = krx_universe_release_check()
        self.assertEqual(payload["symbols"], ["005930", "000660", "005380", "035420", "051910"])
        self.assertFalse(payload["automatic_order"])
        self.assertFalse(payload["automatic_champion_promotion"])

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        try:
            migrate(connection)
            result = SafeToolExecutor(default_tool_registry(connection)).execute(
                ToolRequest("krx_universe_select", {"market": "ALL", "selection_date": "2026-07-30", "size": 2}, "unit", NOW)
            )
            self.assertEqual(result.status, "success")
            self.assertEqual(result.output["selected_size"], 2)
        finally:
            connection.close()

    def test_explicit_symbols_keep_priority_over_dynamic_universe(self) -> None:
        universe_result = KRXUniverseSelector(KRXUniverseFixtureProvider()).select(KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 5), generated_at=NOW)
        resolved = KRXResearchUniverseResolver().resolve(("035420", "005930"), universe_result=universe_result, created_at=NOW)

        self.assertEqual(resolved.symbols, ("035420", "005930"))
        self.assertEqual(resolved.provenance, "explicit_user_provided")

    def test_universe_result_connects_to_multi_symbol_pipeline(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        try:
            migrate(connection)
            universe_result = KRXUniverseSelector(KRXUniverseFixtureProvider()).select(KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 2), generated_at=NOW)
            run = AutonomousMultiSymbolResearchOrchestrator(connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
                DEFAULT_REQUEST_TEXT,
                universe_result=universe_result,
                run_id="unit:dynamic-universe",
                generated_at=NOW,
            )

            self.assertEqual(run.request.universe.universe_id, universe_result.universe_id)
            self.assertEqual(run.request.universe.symbols, universe_result.symbols)
            self.assertEqual(len(run.evidence), 2)
        finally:
            connection.close()


class _TieProvider:
    source = "fixture:tie-provider"

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]:
        return (
            MarketSymbol("005930.KS", "Samsung", "KOSPI"),
            MarketSymbol("000660", "SK Hynix", "KOSPI"),
            MarketSymbol("005380", "Hyundai", "KOSPI"),
        )

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        values = {"000660": 200, "005380": 100, "005930": 100}
        canonical = symbol.upper().replace(".KS", "")
        return _dataset(canonical, start_date, trading_value=values[canonical], volume=10)


class _DirtyProvider(_TieProvider):
    source = "fixture:dirty-provider"

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]:
        return (
            MarketSymbol("005930", "Samsung", "KOSPI"),
            MarketSymbol("000660", "SK Hynix", "KOSPI"),
            MarketSymbol("051910", "LG Chem", "KOSPI"),
            MarketSymbol("005380.KS", "Hyundai", "KOSPI"),
            MarketSymbol("005930.KS", "Samsung duplicate", "KOSPI"),
        )

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        canonical = symbol.upper().replace(".KS", "")
        if canonical == "000660":
            return _dataset(canonical, start_date, trading_value=100, volume=0)
        if canonical == "051910":
            return _dataset(canonical, start_date, trading_value=0, volume=10)
        return _dataset(canonical, start_date, trading_value=200, volume=10)


class _FailingProvider:
    source = "fixture:failing-provider"

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]:
        raise RuntimeError("provider unavailable")


def _dataset(symbol: str, day: str, *, trading_value: int, volume: int) -> MarketDataset:
    bar = MarketBar(day, symbol, 100.0, 101.0, 99.0, 100.0, volume, trading_value)
    metadata = MarketDataMetadata("fixture:krx-universe-test", "KOSPI", "daily", day, day, True, NOW, True)
    return MarketDataset(f"dataset:{symbol}:daily:{day}:{day}", (MarketSymbol(symbol, symbol, "KOSPI"),), (bar,), metadata)


if __name__ == "__main__":
    unittest.main()
