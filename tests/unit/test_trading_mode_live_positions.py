"""Priority 1 / C7 - LIVE -> DEMO position-ownership safety gate.

A LIVE -> DEMO switch is NOT assumed safe. Before it can proceed the
LIVE account is inspected: any BOT_MANAGED open position (which switching
to DEMO would orphan), any UNKNOWN-ownership position, any bot-managed
position missing its STOP protection, or any open bot order blocks the
transition. MANUAL / external positions on their own do not block
(manual isolation).

Interface + assessment only - no real Binance call. Tests use
FakeLivePositionSource.
"""

from __future__ import annotations

import unittest

from gaon.control.live_positions import (
    FakeLivePositionSource,
    LiveOrder,
    LivePosition,
    LivePositionSnapshot,
    PositionOwnership,
    assess_live_to_demo_safety,
)

AT = "2026-09-06T00:00:00Z"


def _pos(ownership, *, symbol="BTCUSDT", has_stop=True, has_tp=True):
    return LivePosition(
        symbol=symbol, side="LONG", qty=0.5, ownership=ownership,
        has_stop=has_stop, has_take_profit=has_tp,
    )


def _snap(positions=(), regular_orders=(), algo_orders=()):
    return LivePositionSnapshot(
        positions=tuple(positions),
        regular_orders=tuple(regular_orders),
        algo_orders=tuple(algo_orders),
        retrieved_at=AT,
    )


class SafeCasesTests(unittest.TestCase):
    def test_empty_live_account_is_safe(self) -> None:
        a = assess_live_to_demo_safety(_snap())
        self.assertTrue(a.safe)
        self.assertEqual(a.blocking_reasons, ())

    def test_manual_external_position_alone_does_not_block(self) -> None:
        a = assess_live_to_demo_safety(_snap(positions=[_pos(PositionOwnership.MANUAL_EXTERNAL)]))
        self.assertTrue(a.safe)
        self.assertIn("manual_external_positions_present", a.notes)


class BlockingCasesTests(unittest.TestCase):
    def test_bot_managed_position_blocks_as_orphan_risk(self) -> None:
        a = assess_live_to_demo_safety(_snap(positions=[_pos(PositionOwnership.BOT_MANAGED)]))
        self.assertFalse(a.safe)
        self.assertIn("bot_managed_live_position_would_be_orphaned", a.blocking_reasons)

    def test_unknown_ownership_position_blocks(self) -> None:
        a = assess_live_to_demo_safety(_snap(positions=[_pos(PositionOwnership.UNKNOWN)]))
        self.assertFalse(a.safe)
        self.assertIn("unknown_ownership_position", a.blocking_reasons)

    def test_bot_managed_position_without_stop_blocks_even_if_also_orphan_reason(self) -> None:
        a = assess_live_to_demo_safety(_snap(positions=[_pos(PositionOwnership.BOT_MANAGED, has_stop=False)]))
        self.assertFalse(a.safe)
        self.assertIn("bot_managed_position_without_stop", a.blocking_reasons)

    def test_open_bot_algo_order_blocks(self) -> None:
        order = LiveOrder(order_id="algo-1", symbol="BTCUSDT", kind="STOP_MARKET", owner=PositionOwnership.BOT_MANAGED, open=True)
        a = assess_live_to_demo_safety(_snap(algo_orders=[order]))
        self.assertFalse(a.safe)
        self.assertIn("open_bot_orders_present", a.blocking_reasons)

    def test_open_bot_regular_order_blocks(self) -> None:
        order = LiveOrder(order_id="ord-1", symbol="BTCUSDT", kind="LIMIT", owner=PositionOwnership.BOT_MANAGED, open=True)
        a = assess_live_to_demo_safety(_snap(regular_orders=[order]))
        self.assertFalse(a.safe)
        self.assertIn("open_bot_orders_present", a.blocking_reasons)

    def test_closed_or_manual_orders_do_not_block(self) -> None:
        closed = LiveOrder(order_id="o1", symbol="BTCUSDT", kind="LIMIT", owner=PositionOwnership.BOT_MANAGED, open=False)
        manual = LiveOrder(order_id="o2", symbol="BTCUSDT", kind="LIMIT", owner=PositionOwnership.MANUAL_EXTERNAL, open=True)
        a = assess_live_to_demo_safety(_snap(regular_orders=[closed, manual]))
        self.assertTrue(a.safe)


class SourceInterfaceTests(unittest.TestCase):
    def test_fake_source_returns_its_snapshot(self) -> None:
        snap = _snap(positions=[_pos(PositionOwnership.MANUAL_EXTERNAL)])
        src = FakeLivePositionSource(snap)
        self.assertEqual(src.snapshot(), snap)


if __name__ == "__main__":
    unittest.main()
