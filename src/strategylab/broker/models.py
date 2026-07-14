"""Broker interface models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"


@dataclass(frozen=True)
class BrokerOrder:
    symbol: str
    side: OrderSide
    quantity: int
    limit_price: float | None = None


@dataclass(frozen=True)
class BrokerFill:
    order: BrokerOrder
    status: OrderStatus
    timestamp: datetime
    fill_price: float | None = None
    reason: str = ""

