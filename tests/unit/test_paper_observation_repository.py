"""Unit tests for the Paper<->Gaon feedback-loop observation ledger
(``gaon.runtime.paper_observation_repository`` /
``gaon.runtime.migrations._upgrade_v44_to_v45``).
"""

from __future__ import annotations

import unittest

from gaon.runtime.paper_observation_repository import PaperObservationSQLiteRepository
from gaon.runtime.storage import RuntimeStateStore

FAMILY_ID = "csm-48h-long"


def _observation(**overrides: object) -> dict:
    base = {
        "family_id": FAMILY_ID,
        "strategy_version_id": "strategy-version:abc123",
        "spec_fingerprint": "fp-csm48h-v1",
        "direction": "LONG",
        "symbol": "QNTUSDT",
        "signal_at": "2026-10-20T00:00:00Z",
        "status": "signal_only",
        "reason": None,
    }
    base.update(overrides)
    return base


class PaperObservationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.repo = PaperObservationSQLiteRepository(self.store._connection)

    def test_insert_requires_all_required_fields(self) -> None:
        incomplete = _observation()
        del incomplete["symbol"]
        with self.assertRaises(KeyError):
            self.repo.insert(incomplete, created_at="2026-10-20T00:00:01Z")

    def test_insert_and_list_round_trips(self) -> None:
        obs_id = self.repo.insert(_observation(), created_at="2026-10-20T00:00:01Z")
        self.assertIsInstance(obs_id, int)
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "QNTUSDT")
        self.assertEqual(rows[0]["status"], "signal_only")
        self.assertIsNone(rows[0]["pnl"])

    def test_list_is_isolated_per_family(self) -> None:
        self.repo.insert(_observation(), created_at="2026-10-20T00:00:01Z")
        self.repo.insert(_observation(family_id="other-family"), created_at="2026-10-20T00:00:02Z")
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 1)
        self.assertEqual(len(self.repo.list_for_family("other-family")), 1)
        self.assertEqual(len(self.repo.list_for_family("nonexistent-family")), 0)

    def test_aggregate_counts_only_closed_trades_with_pnl(self) -> None:
        self.repo.insert(_observation(status="signal_only"), created_at="t1")
        self.repo.insert(_observation(status="entry_blocked", reason="min_notional"), created_at="t2")
        self.repo.insert(_observation(status="closed", pnl=10.0, pnl_pct=0.02, symbol="SOLUSDT"), created_at="t3")
        self.repo.insert(_observation(status="closed", pnl=-4.0, pnl_pct=-0.01, symbol="ETHUSDT"), created_at="t4")

        agg = self.repo.aggregate_for_family(FAMILY_ID)
        self.assertEqual(agg["closed_trade_count"], 2)
        self.assertEqual(agg["win_count"], 1)
        self.assertEqual(agg["loss_count"], 1)
        self.assertAlmostEqual(agg["win_rate"], 0.5)
        self.assertAlmostEqual(agg["profit_factor"], 2.5)
        self.assertAlmostEqual(agg["total_pnl"], 6.0)
        self.assertEqual(agg["status_counts"]["signal_only"], 1)
        self.assertEqual(agg["status_counts"]["entry_blocked"], 1)
        self.assertEqual(agg["status_counts"]["closed"], 2)

    def test_aggregate_profit_factor_is_none_not_infinite_when_no_losses(self) -> None:
        self.repo.insert(_observation(status="closed", pnl=5.0, pnl_pct=0.01), created_at="t1")
        agg = self.repo.aggregate_for_family(FAMILY_ID)
        self.assertIsNone(agg["profit_factor"])

    def test_aggregate_on_empty_family_returns_nones_not_errors(self) -> None:
        agg = self.repo.aggregate_for_family("never-reported")
        self.assertEqual(agg["closed_trade_count"], 0)
        self.assertIsNone(agg["win_rate"])
        self.assertIsNone(agg["profit_factor"])
        self.assertEqual(agg["total_pnl"], 0.0)

    def test_durable_across_a_fresh_connection_handle(self) -> None:
        self.repo.insert(_observation(), created_at="t1")
        fresh = PaperObservationSQLiteRepository(self.store._connection)
        self.assertEqual(len(fresh.list_for_family(FAMILY_ID)), 1)

    def test_resending_identical_closed_report_does_not_double_count(self) -> None:
        """Regression: a client that times out waiting for a response this
        insert already committed (e.g. SQLite write-lock contention) will
        resend the exact same payload. That must not double-count the trade
        in aggregate_for_family() - schema v46's UNIQUE index on
        (family_id, symbol, status, entry_at, exit_at) makes a repeat insert
        of the identical stage an idempotent no-op."""
        closed = _observation(
            status="closed", symbol="SOLUSDT", entry_at="2026-10-20T00:00:00Z",
            exit_at="2026-10-22T00:00:00Z", pnl=10.0, pnl_pct=0.02,
        )
        first_id = self.repo.insert(closed, created_at="t1")
        second_id = self.repo.insert(dict(closed), created_at="t2")  # resent as a fresh dict, same content
        self.assertEqual(first_id, second_id)
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertEqual(len(rows), 1)
        agg = self.repo.aggregate_for_family(FAMILY_ID)
        self.assertEqual(agg["closed_trade_count"], 1)
        self.assertAlmostEqual(agg["total_pnl"], 10.0)

    def test_two_distinct_closed_trades_for_the_same_symbol_both_count(self) -> None:
        """The idempotency key must not be so broad that a genuinely new
        trade (different entry_at/exit_at - the next 48h rebalance cycle)
        on the same symbol gets silently dropped."""
        self.repo.insert(
            _observation(status="closed", symbol="SOLUSDT", entry_at="t1", exit_at="t2", pnl=10.0, pnl_pct=0.02),
            created_at="r1",
        )
        self.repo.insert(
            _observation(status="closed", symbol="SOLUSDT", entry_at="t3", exit_at="t4", pnl=-5.0, pnl_pct=-0.01),
            created_at="r2",
        )
        agg = self.repo.aggregate_for_family(FAMILY_ID)
        self.assertEqual(agg["closed_trade_count"], 2)
        self.assertAlmostEqual(agg["total_pnl"], 5.0)

    def test_resending_identical_open_report_is_not_blocked_by_the_unique_index(self) -> None:
        """status='open' always has exit_at=NULL, and SQLite does not treat
        two NULLs as equal in a UNIQUE index - so a resent 'open' report is
        NOT caught by this index. That's an accepted, lower-severity gap:
        open rows never contribute to the PnL/win-rate aggregate, so a
        duplicate open row cannot double-count anything that matters."""
        open_obs = _observation(status="open", symbol="SOLUSDT", entry_at="2026-10-20T00:00:00Z")
        self.repo.insert(open_obs, created_at="t1")
        self.repo.insert(dict(open_obs), created_at="t2")
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 2)
        agg = self.repo.aggregate_for_family(FAMILY_ID)
        self.assertEqual(agg["closed_trade_count"], 0)  # unaffected either way


if __name__ == "__main__":
    unittest.main()
