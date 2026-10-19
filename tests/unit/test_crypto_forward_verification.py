from __future__ import annotations

import pathlib
import sqlite3
import unittest

import gaon.research.crypto_forward_verification as crypto_fv_module
from gaon.research.crypto_forward_verification import (
    STRATEGY_SPEC,
    STRATEGY_VERSION,
    CryptoForwardVerificationRepository,
    RebalanceDecision,
    classify_btc_regime,
    count_candle_gaps,
    count_duplicate_timestamps,
    decide_rebalance,
    ensure_schema,
    funding_cost_pct,
    health_check,
    metric,
    poll_once,
    promotion_readiness,
    register_version,
    rolling_mean_dollar_volume,
    spec_version_hash,
    to_5m_bars,
)


def _one_minute_rows(n: int, *, start_ms: int, base_price: float, drift_per_min: float, volume: float = 1000.0) -> list[tuple]:
    rows = []
    price = base_price
    for i in range(n):
        price = price * (1 + drift_per_min)
        rows.append((start_ms + i * 60_000, price, price * 1.001, price * 0.999, price, volume))
    return rows


class SpecAndPureHelperTests(unittest.TestCase):
    def test_version_hash_is_deterministic_and_changes_with_the_spec(self) -> None:
        h1 = spec_version_hash(STRATEGY_SPEC)
        h2 = spec_version_hash(dict(STRATEGY_SPEC))
        self.assertEqual(h1, h2)
        changed = dict(STRATEGY_SPEC)
        changed["hold_bars"] = 999
        self.assertNotEqual(spec_version_hash(changed), h1)

    def test_strategy_version_embeds_the_spec_hash(self) -> None:
        self.assertIn(spec_version_hash(STRATEGY_SPEC), STRATEGY_VERSION)

    def test_to_5m_bars_only_accepts_contiguous_groups_of_five(self) -> None:
        rows = _one_minute_rows(10, start_ms=0, base_price=100.0, drift_per_min=0.0)
        bars = to_5m_bars(rows)
        self.assertEqual(len(bars), 2)
        gapped = rows[:3] + rows[4:]
        self.assertEqual(to_5m_bars(gapped), [])

    def test_rolling_mean_dollar_volume_is_none_until_window_fills(self) -> None:
        bars = [(i, 1, 1, 1, 100.0, 10.0) for i in range(5)]
        out = rolling_mean_dollar_volume(bars, window=3)
        self.assertEqual(out[:2], [None, None])
        self.assertEqual(out[2], 1000.0)

    def test_classify_btc_regime_thresholds(self) -> None:
        self.assertEqual(classify_btc_regime(0.02), "up")
        self.assertEqual(classify_btc_regime(-0.02), "down")
        self.assertEqual(classify_btc_regime(0.001), "flat")
        self.assertEqual(classify_btc_regime(None), "unknown")

    def test_funding_cost_only_counts_events_inside_the_holding_window(self) -> None:
        events = [(100, 0.0001), (500, 0.0002), (999, 0.0003)]
        cost = funding_cost_pct(events, start_ms=100, end_ms=999)
        self.assertAlmostEqual(cost, -(0.0001 * 100 + 0.0002 * 100))

    def test_metric_handles_empty_and_computes_pf_and_mdd(self) -> None:
        self.assertEqual(metric([])["n"], 0)
        m = metric([1.0, -0.5, 2.0, -3.0])
        self.assertEqual(m["n"], 4)
        self.assertAlmostEqual(m["pf"], round(3.0 / 3.5, 3))
        self.assertLess(m["mdd_pct"], 0)

    def test_promotion_readiness_lists_every_unmet_bar(self) -> None:
        trades = [{"rebalance_index": i, "btc_regime": "up"} for i in range(5)]
        r = promotion_readiness(trades)
        self.assertFalse(r["eligible_for_promotion_review"])
        self.assertTrue(any("forward trades" in b for b in r["blockers"]))
        self.assertTrue(any("independent rebalances" in b for b in r["blockers"]))
        self.assertTrue(any("regime buckets" in b for b in r["blockers"]))

    def test_promotion_readiness_clears_when_every_bar_is_met(self) -> None:
        trades = []
        for i in range(34):
            trades.append({"rebalance_index": i, "btc_regime": "up" if i % 2 == 0 else "down"})
        for _ in range(100 - 34):
            trades.append({"rebalance_index": 998, "btc_regime": "flat"})
        r = promotion_readiness(trades)
        self.assertEqual(r["forward_trades"], 100)
        self.assertGreaterEqual(r["independent_rebalances"], 30)
        self.assertTrue(r["eligible_for_promotion_review"])
        self.assertEqual(r["blockers"], ["none - eligible for a human promotion review (this is NOT a promotion)"])


class DecideRebalanceTests(unittest.TestCase):
    def _bars_for(self, n: int, base: float, drift: float) -> list[tuple]:
        bars = []
        price = base
        for i in range(n):
            price = price * (1 + drift)
            bars.append((i * 300_000, price, price, price, price, 1_000_000.0))
        return bars

    def test_returns_none_without_enough_history(self) -> None:
        bars = {"BTCUSDT": self._bars_for(10, 100, 0.0)}
        self.assertIsNone(decide_rebalance(bars, decision_idx=5))

    def test_picks_the_top_quartile_by_trailing_return_and_classifies_regime(self) -> None:
        lookback = int(STRATEGY_SPEC["lookback_bars"])
        liq_window = int(STRATEGY_SPEC["liquidity_window_bars"])
        n = lookback + liq_window + 5
        decision_idx = n - 1
        bars_by_symbol = {"BTCUSDT": self._bars_for(n, 100.0, 0.0005)}
        # 20 eligible symbols with distinct drift so rank is unambiguous.
        universe = list(STRATEGY_SPEC["universe"])
        for i, sym in enumerate(universe):
            bars_by_symbol[sym] = self._bars_for(n, 100.0, 0.0005 + i * 0.0002)
        decision = decide_rebalance(bars_by_symbol, decision_idx=decision_idx)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.btc_regime, "up")
        # The highest-drift symbols should dominate the picked top quartile.
        ranked_by_drift = universe[::-1]
        top_by_drift = set(ranked_by_drift[: len(decision.picked)])
        self.assertTrue(set(decision.picked).issubset(set(universe)))
        self.assertGreater(len(set(decision.picked) & top_by_drift), 0)

    def test_liquidity_floor_excludes_thin_symbols(self) -> None:
        lookback = int(STRATEGY_SPEC["lookback_bars"])
        liq_window = int(STRATEGY_SPEC["liquidity_window_bars"])
        n = lookback + liq_window + 5
        decision_idx = n - 1
        universe = list(STRATEGY_SPEC["universe"])
        bars_by_symbol = {}
        for i, sym in enumerate(universe):
            price = 100.0
            bars = []
            for k in range(n):
                price *= 1 + 0.0003 + i * 0.0001
                volume = 1.0 if sym == universe[0] else 1_000_000.0  # starve one symbol of liquidity
                bars.append((k * 300_000, price, price, price, price, volume))
            bars_by_symbol[sym] = bars
        decision = decide_rebalance(bars_by_symbol, decision_idx=decision_idx)
        self.assertIsNotNone(decision)
        self.assertNotIn(universe[0], decision.picked)
        self.assertLess(decision.eligible_count, len(universe))


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = CryptoForwardVerificationRepository(self.connection)

    def test_upsert_bars_is_idempotent(self) -> None:
        rows = _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0)
        self.repo.upsert_bars("BTCUSDT", rows)
        self.repo.upsert_bars("BTCUSDT", rows)  # re-ingesting the same rows must not duplicate
        self.assertEqual(len(self.repo.load_1m_rows("BTCUSDT")), 5)

    def test_register_version_is_idempotent_and_never_overwrites_started_at(self) -> None:
        register_version(self.connection, now_iso="2026-01-01T00:00:00Z")
        register_version(self.connection, now_iso="2026-01-02T00:00:00Z")
        self.assertEqual(self.repo.version_started_at(), "2026-01-01T00:00:00Z")

    def test_open_trade_is_idempotent_no_duplicate_entries(self) -> None:
        self.repo.open_trade(rebalance_index=0, symbol="BTCUSDT", entry_time_ms=100, exit_time_ms=200, entry_price=50.0, btc_regime="up")
        self.repo.open_trade(rebalance_index=0, symbol="BTCUSDT", entry_time_ms=999, exit_time_ms=999, entry_price=999.0, btc_regime="down")
        trades = self.repo.all_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_price"], 50.0)  # the second (duplicate) open_trade call never overwrote it

    def test_close_trade_only_closes_an_open_matching_trade_no_duplicate_exits(self) -> None:
        self.repo.open_trade(rebalance_index=0, symbol="BTCUSDT", entry_time_ms=100, exit_time_ms=200, entry_price=50.0, btc_regime="up")
        self.repo.close_trade(rebalance_index=0, symbol="BTCUSDT", exit_price=55.0, price_pct=10.0, funding_pct=-0.1)
        self.repo.close_trade(rebalance_index=0, symbol="BTCUSDT", exit_price=999.0, price_pct=999.0, funding_pct=999.0)
        trades = self.repo.all_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["status"], "closed")
        self.assertEqual(trades[0]["price_pct"], 10.0)  # the second close_trade call was a no-op (status already 'closed')


class PollOnceEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = CryptoForwardVerificationRepository(self.connection)

    def _dataset(self, *, extra_5m_bars: int) -> dict[str, list[tuple]]:
        lookback, liq_window = (int(STRATEGY_SPEC[k]) for k in ("lookback_bars", "liquidity_window_bars"))
        n_5m_bars = lookback + liq_window + extra_5m_bars
        n_minutes = n_5m_bars * 5
        data = {}
        for i, sym in enumerate(STRATEGY_SPEC["universe"]):
            data[sym] = _one_minute_rows(n_minutes, start_ms=0, base_price=100.0, drift_per_min=0.00002 * (i + 1), volume=10_000.0)
        return data

    def test_first_poll_opens_a_rebalance_once_warmup_is_satisfied_and_never_fabricates_before_that(self) -> None:
        # Only enough data to cover warmup + the entry bar - the exit bar
        # (hold_bars later) is NOT yet available, matching how data arrives
        # gradually in production; nothing should be closed yet.
        data = self._dataset(extra_5m_bars=2)
        calls = {"klines": 0}

        def fetch_klines(sym: str) -> list[tuple]:
            calls["klines"] += 1
            return data[sym]

        result = poll_once(self.repo, fetch_klines=fetch_klines, fetch_funding=lambda sym, start_ms: [], now_iso="2026-01-01T00:00:00Z")
        self.assertGreaterEqual(result["opened"], 1)
        trades = self.repo.all_trades()
        self.assertTrue(all(t["status"] == "open" for t in trades))
        self.assertGreater(len(trades), 0)

    def test_insufficient_warmup_opens_nothing(self) -> None:
        short_data = {sym: rows[: len(rows) // 4] for sym, rows in self._dataset(extra_5m_bars=2).items()}

        result = poll_once(self.repo, fetch_klines=lambda sym: short_data[sym], fetch_funding=lambda sym, start_ms: [], now_iso="2026-01-01T00:00:00Z")
        self.assertEqual(result["opened"], 0)
        self.assertEqual(self.repo.all_trades(), [])

    def test_second_poll_closes_trades_once_due_and_applies_funding(self) -> None:
        opening_data = self._dataset(extra_5m_bars=2)
        poll_once(self.repo, fetch_klines=lambda sym: opening_data[sym], fetch_funding=lambda sym, start_ms: [], now_iso="2026-01-01T00:00:00Z")
        opened_trades = self.repo.all_trades()
        self.assertTrue(opened_trades)
        self.assertTrue(all(t["status"] == "open" for t in opened_trades))

        hold = int(STRATEGY_SPEC["hold_bars"])
        full_data = self._dataset(extra_5m_bars=hold + 2)
        funding_calls = []

        def fetch_funding(sym: str, start_ms: int) -> list[tuple[int, float]]:
            funding_calls.append(sym)
            return [(start_ms + 1000, 0.0001)]

        poll_once(self.repo, fetch_klines=lambda sym: full_data[sym], fetch_funding=fetch_funding, now_iso="2026-01-03T01:00:00Z")
        closed_trades = [t for t in self.repo.all_trades() if t["status"] == "closed"]
        self.assertTrue(closed_trades)
        self.assertTrue(funding_calls)
        self.assertTrue(any(t["funding_pct"] is not None and t["funding_pct"] != 0 for t in closed_trades))

    def test_poll_is_idempotent_if_called_twice_with_the_same_data(self) -> None:
        data = self._dataset(extra_5m_bars=2)
        poll_once(self.repo, fetch_klines=lambda sym: data[sym], fetch_funding=lambda sym, start_ms: [], now_iso="2026-01-01T00:00:00Z")
        n1 = len(self.repo.all_trades())
        poll_once(self.repo, fetch_klines=lambda sym: data[sym], fetch_funding=lambda sym, start_ms: [], now_iso="2026-01-01T00:05:00Z")
        n2 = len(self.repo.all_trades())
        self.assertEqual(n1, n2)  # same rebalance index, same symbols -> no duplicate trades


class GapAndDuplicateDetectionTests(unittest.TestCase):
    def test_count_candle_gaps_finds_missing_minutes(self) -> None:
        rows = _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0)
        self.assertEqual(count_candle_gaps(rows), 0)
        with_gap = rows[:2] + rows[3:]  # drop the middle minute
        self.assertEqual(count_candle_gaps(with_gap), 1)

    def test_count_duplicate_timestamps_is_zero_for_well_formed_rows(self) -> None:
        rows = _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0)
        self.assertEqual(count_duplicate_timestamps(rows), 0)
        with_dup = rows + [rows[0]]
        self.assertEqual(count_duplicate_timestamps(with_dup), 1)


class HealthCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = CryptoForwardVerificationRepository(self.connection)
        register_version(self.connection, now_iso="2026-01-01T00:00:00Z")

    def test_no_data_at_all_is_reported_as_stale_not_crashed(self) -> None:
        result = health_check(self.repo, now_ms=1_000_000)
        self.assertIn(result["status"], ("WARNING", "ERROR"))
        self.assertEqual(len(result["stale_symbols"]), len(STRATEGY_SPEC["universe"]))

    def test_fresh_full_universe_with_no_poll_history_is_ok_or_warns_only_about_missing_poll_events(self) -> None:
        now_ms = 10_000_000_000
        for sym in STRATEGY_SPEC["universe"]:
            rows = _one_minute_rows(5, start_ms=now_ms - 4 * 60_000, base_price=100.0, drift_per_min=0.0)
            self.repo.upsert_bars(sym, rows)
        result = health_check(self.repo, now_ms=now_ms, max_staleness_seconds=900.0)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["stale_symbols"], [])
        self.assertEqual(result["candle_gaps_total"], 0)
        self.assertEqual(result["duplicate_timestamps_total"], 0)
        self.assertTrue(result["version_consistent"])

    def test_stale_data_beyond_the_threshold_is_flagged(self) -> None:
        rows = _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0)
        self.repo.upsert_bars("BTCUSDT", rows)
        result = health_check(self.repo, now_ms=10_000_000_000, max_staleness_seconds=900.0)
        self.assertIn("BTCUSDT", result["stale_symbols"])
        self.assertTrue(any("stale" in w for w in result["warnings"]))

    def test_recent_poll_errors_are_surfaced(self) -> None:
        now_ms = 10_000_000_000
        for sym in STRATEGY_SPEC["universe"]:
            self.repo.upsert_bars(sym, _one_minute_rows(5, start_ms=now_ms - 4 * 60_000, base_price=100.0, drift_per_min=0.0))
        self.repo.record_poll_event(ts_ms=now_ms - 60_000, ok=False, error="URLError: timed out")
        result = health_check(self.repo, now_ms=now_ms, poll_error_lookback_seconds=3600.0)
        self.assertEqual(result["recent_poll_errors_count"], 1)
        self.assertTrue(any("poll error" in w for w in result["warnings"]))

    def test_version_drift_is_detected_as_a_problem(self) -> None:
        # Simulate corruption: the stored spec no longer matches the frozen
        # in-code STRATEGY_SPEC for the same version string.
        with self.connection:
            self.connection.execute(
                "UPDATE crypto_fv_versions SET spec_json = ? WHERE version = ?",
                ('{"tampered": true}', STRATEGY_VERSION),
            )
        for sym in STRATEGY_SPEC["universe"]:
            self.repo.upsert_bars(sym, _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0))
        result = health_check(self.repo, now_ms=10_000_000_000)
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(result["version_consistent"])

    def test_read_only_connection_can_run_health_check(self) -> None:
        # Mirrors the Gaon admin page's access pattern: a separate mode=ro
        # connection must be able to run health_check without ever writing.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "fv.sqlite"
            rw_connection = sqlite3.connect(str(db_path))
            try:
                rw_repo = CryptoForwardVerificationRepository(rw_connection)
                rw_repo.upsert_bars("BTCUSDT", _one_minute_rows(5, start_ms=0, base_price=100.0, drift_per_min=0.0))
            finally:
                rw_connection.close()

            ro_connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                ro_repo = CryptoForwardVerificationRepository(ro_connection, ensure_schema_=False)
                result = health_check(ro_repo, now_ms=10_000_000_000)
                self.assertIn(result["status"], ("OK", "WARNING", "ERROR"))
            finally:
                ro_connection.close()


class PollEventLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = CryptoForwardVerificationRepository(self.connection)

    def test_record_and_fetch_poll_events_round_trip(self) -> None:
        self.repo.record_poll_event(ts_ms=100, ok=True, opened=1, closed=0, bars_collected_btc=10)
        self.repo.record_poll_event(ts_ms=200, ok=False, error="boom")
        events = self.repo.recent_poll_events(since_ms=0)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0]["ok"])
        self.assertFalse(events[1]["ok"])
        self.assertEqual(events[1]["error"], "boom")

    def test_recent_poll_events_respects_the_since_cutoff(self) -> None:
        self.repo.record_poll_event(ts_ms=100, ok=True)
        self.repo.record_poll_event(ts_ms=5000, ok=True)
        self.assertEqual(len(self.repo.recent_poll_events(since_ms=1000)), 1)


class OrderExecutionPathSeparationTests(unittest.TestCase):
    """Regression tests (operational-reliability requirement 5): this
    research module must stay structurally incapable of touching the real
    order-execution path, no matter what future changes are made to it."""

    @staticmethod
    def _source_without_module_docstring() -> str:
        # The module's own top-of-file docstring documents, in prose, the
        # safety boundary it upholds ("never imports gaon.adapters.binance",
        # "never touches /opt/binance-trading") - exactly the forbidden
        # substrings below, but as a negative claim, not a reference. Strip
        # it so this test scans only executable code.
        source = pathlib.Path(crypto_fv_module.__file__).read_text(encoding="utf-8")
        first = source.find('"""')
        second = source.find('"""', first + 3)
        return source[second + 3:] if first != -1 and second != -1 else source

    def test_module_has_no_binance_order_capable_imports_or_calls(self) -> None:
        source = self._source_without_module_docstring()
        forbidden = (
            "gaon.adapters.binance",
            "binance.client",
            "python-binance",
            "/opt/binance-trading",
            "futures_create_order",
            "futures_cancel_order",
            "new_order(",
            "place_order",
            "AsyncClient(",
            "Client(",
        )
        for needle in forbidden:
            self.assertNotIn(needle, source, f"forbidden order-capable reference found: {needle!r}")

    def test_only_the_two_public_unauthenticated_endpoints_are_ever_requested(self) -> None:
        source = self._source_without_module_docstring()
        for line in source.splitlines():
            if "fapi.binance.com" in line:
                self.assertTrue(
                    "/fapi/v1/klines" in line or "/fapi/v1/fundingRate" in line or line.strip().startswith(("KLINES_URL", "FUNDING_URL")),
                    f"unexpected Binance endpoint referenced: {line.strip()!r}",
                )

    def test_no_api_key_or_secret_credential_is_ever_read_from_the_environment(self) -> None:
        source = self._source_without_module_docstring()
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)
        for needle in ("API_KEY", "API_SECRET", "apikey", "api_secret"):
            self.assertNotIn(needle, source)

    def test_fetchers_only_hit_the_declared_public_hosts(self) -> None:
        self.assertTrue(crypto_fv_module.KLINES_URL.startswith("https://fapi.binance.com/fapi/v1/klines"))
        self.assertTrue(crypto_fv_module.FUNDING_URL.startswith("https://fapi.binance.com/fapi/v1/fundingRate"))


class HealthCheckCliWiringTests(unittest.TestCase):
    def test_cli_health_subcommand_reports_warning_and_nonzero_exit_on_empty_db(self) -> None:
        import shutil
        import tempfile
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))
        db_path = f"{tmp_dir}/health_cli.sqlite"

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["crypto-forward-verification-health", "--db", db_path])
        self.assertEqual(exit_code, 1)  # empty/new DB is never "OK"
        self.assertIn("status", output.getvalue())


if __name__ == "__main__":
    unittest.main()
