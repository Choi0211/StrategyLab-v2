"""Broker adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from strategylab.broker.models import BrokerFill, BrokerOrder


class BrokerAdapter(ABC):
    """Safe broker adapter interface."""

    @abstractmethod
    def submit_order(self, order: BrokerOrder) -> BrokerFill:
        """Submit order and return fill/rejection."""

