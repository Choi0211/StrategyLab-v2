"""Paper trading broker adapter."""

from __future__ import annotations

from datetime import datetime

from strategylab.broker.interface import BrokerAdapter
from strategylab.broker.models import BrokerFill, BrokerOrder, OrderStatus


class PaperBrokerAdapter(BrokerAdapter):
    """Deterministic paper adapter with provided marks."""

    def __init__(self, marks: dict[str, float]) -> None:
        self.marks = marks

    def submit_order(self, order: BrokerOrder) -> BrokerFill:
        if order.quantity <= 0:
            return BrokerFill(order, OrderStatus.REJECTED, datetime(2026, 1, 1), reason="quantity must be positive")
        price = self.marks.get(order.symbol)
        if price is None:
            return BrokerFill(order, OrderStatus.REJECTED, datetime(2026, 1, 1), reason="missing mark")
        if order.limit_price is not None:
            if order.side.value == "buy" and price > order.limit_price:
                return BrokerFill(order, OrderStatus.REJECTED, datetime(2026, 1, 1), reason="limit not met")
            if order.side.value == "sell" and price < order.limit_price:
                return BrokerFill(order, OrderStatus.REJECTED, datetime(2026, 1, 1), reason="limit not met")
        return BrokerFill(order, OrderStatus.FILLED, datetime(2026, 1, 1), fill_price=price, reason="paper fill")

