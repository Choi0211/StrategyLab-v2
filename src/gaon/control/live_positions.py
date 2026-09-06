"""Priority 1 / C7 - LIVE -> DEMO position-ownership safety gate.

A LIVE -> DEMO switch is never assumed safe. Before the transition
machine's ``verify_positions_safe`` step may pass for a LIVE source, the
LIVE account is inspected:

  - a BOT_MANAGED open position would be ORPHANED by switching to DEMO
    (the bot loses the connection that manages it)          -> BLOCK
  - an UNKNOWN-ownership position cannot be reasoned about   -> BLOCK
  - a BOT_MANAGED position missing its STOP protection       -> BLOCK
  - any OPEN bot-owned order (regular or algo STOP/TP)        -> BLOCK

MANUAL / external positions and orders on their own do NOT block (manual
isolation) - they are only noted.

Interface + pure assessment. No real Binance call; tests use
``FakeLivePositionSource``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PositionOwnership(str, Enum):
    BOT_MANAGED = "bot_managed"
    MANUAL_EXTERNAL = "manual_external"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LivePosition:
    symbol: str
    side: str
    qty: float
    ownership: PositionOwnership
    has_stop: bool
    has_take_profit: bool


@dataclass(frozen=True)
class LiveOrder:
    order_id: str
    symbol: str
    kind: str  # LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET / ...
    owner: PositionOwnership
    open: bool


@dataclass(frozen=True)
class LivePositionSnapshot:
    positions: tuple[LivePosition, ...]
    regular_orders: tuple[LiveOrder, ...]
    algo_orders: tuple[LiveOrder, ...]
    retrieved_at: str


class LivePositionSource(Protocol):
    def snapshot(self) -> LivePositionSnapshot: ...


class FakeLivePositionSource:
    def __init__(self, snapshot: LivePositionSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> LivePositionSnapshot:
        return self._snapshot


@dataclass(frozen=True)
class LiveToDemoAssessment:
    safe: bool
    blocking_reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def assess_live_to_demo_safety(snapshot: LivePositionSnapshot) -> LiveToDemoAssessment:
    reasons: list[str] = []
    notes: list[str] = []

    bot_positions = [p for p in snapshot.positions if p.ownership is PositionOwnership.BOT_MANAGED]
    unknown_positions = [p for p in snapshot.positions if p.ownership is PositionOwnership.UNKNOWN]
    manual_positions = [p for p in snapshot.positions if p.ownership is PositionOwnership.MANUAL_EXTERNAL]

    if bot_positions:
        reasons.append("bot_managed_live_position_would_be_orphaned")
        if any(not p.has_stop for p in bot_positions):
            reasons.append("bot_managed_position_without_stop")
    if unknown_positions:
        reasons.append("unknown_ownership_position")
    if manual_positions:
        notes.append("manual_external_positions_present")

    open_bot_orders = [
        o
        for o in (*snapshot.regular_orders, *snapshot.algo_orders)
        if o.open and o.owner is PositionOwnership.BOT_MANAGED
    ]
    if open_bot_orders:
        reasons.append("open_bot_orders_present")

    # de-dup, stable order
    deduped = tuple(dict.fromkeys(reasons))
    return LiveToDemoAssessment(safe=not deduped, blocking_reasons=deduped, notes=tuple(dict.fromkeys(notes)))
