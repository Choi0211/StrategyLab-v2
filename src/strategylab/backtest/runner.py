"""Deterministic backtest runner foundation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import hashlib
import json

from strategylab.backtest.models import BacktestConfig, BacktestResult, EquityCurvePoint, TradeRecord, TradeSide
from strategylab.market import MarketBar, MarketDataset
from strategylab.strategies import Signal, SignalType, StrategyConfig


class BacktestRunner(ABC):
    """Backtest runner interface."""

    @abstractmethod
    def run(
        self,
        dataset: MarketDataset,
        signals: tuple[Signal, ...],
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
    ) -> BacktestResult:
        """Run a backtest and return canonical output."""


class SimpleBacktestRunner(BacktestRunner):
    """A deterministic one-unit signal runner for Sprint 4 fixtures."""

    def run(
        self,
        dataset: MarketDataset,
        signals: tuple[Signal, ...],
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
    ) -> BacktestResult:
        bars_by_key: dict[tuple[str, datetime], MarketBar] = {(bar.symbol, bar.timestamp): bar for bar in dataset.bars}
        cash = backtest_config.initial_capital
        holdings: dict[str, int] = {}
        trades: list[TradeRecord] = []
        equity_curve: list[EquityCurvePoint] = []
        max_equity = backtest_config.initial_capital

        for signal in sorted(signals, key=lambda item: (item.timestamp, item.symbol, item.signal_type.value)):
            bar = bars_by_key.get((signal.symbol, signal.timestamp))
            if bar is None:
                continue

            if signal.signal_type is SignalType.BUY:
                trade = self._buy(signal, bar.close, cash, backtest_config)
                if trade is not None:
                    cost = trade.price * trade.quantity + trade.fees + trade.slippage
                    cash -= cost
                    holdings[signal.symbol] = holdings.get(signal.symbol, 0) + trade.quantity
                    trades.append(trade)
            elif signal.signal_type is SignalType.SELL and holdings.get(signal.symbol, 0) > 0:
                trade = self._sell(signal, bar.close, holdings[signal.symbol], backtest_config)
                proceeds = trade.price * trade.quantity - trade.fees - trade.slippage
                cash += proceeds
                holdings[signal.symbol] -= trade.quantity
                trades.append(trade)

            holdings_value = self._holdings_value(holdings, bars_by_key, signal.timestamp)
            total_equity = cash + holdings_value
            max_equity = max(max_equity, total_equity)
            drawdown = 0.0 if max_equity == 0 else (total_equity - max_equity) / max_equity
            equity_curve.append(
                EquityCurvePoint(
                    timestamp=signal.timestamp,
                    cash=round(cash, 6),
                    holdings_value=round(holdings_value, 6),
                    total_equity=round(total_equity, 6),
                    drawdown=round(drawdown, 6),
                )
            )

        result_id = self._result_id(dataset, signals, strategy_config, backtest_config)
        return BacktestResult(
            result_id=result_id,
            config=backtest_config,
            trades=tuple(trades),
            equity_curve=tuple(equity_curve),
        )

    def _buy(
        self,
        signal: Signal,
        close_price: float,
        cash: float,
        config: BacktestConfig,
    ) -> TradeRecord | None:
        price = close_price * (1.0 + config.slippage_rate)
        quantity = config.quantity_per_signal
        fees = price * quantity * config.transaction_cost_rate
        slippage = close_price * quantity * config.slippage_rate
        total_cost = price * quantity + fees + slippage
        if total_cost > cash:
            return None
        return TradeRecord(
            timestamp=signal.timestamp,
            symbol=signal.symbol,
            side=TradeSide.BUY,
            price=round(price, 6),
            quantity=quantity,
            fees=round(fees, 6),
            slippage=round(slippage, 6),
            reason=signal.reason,
        )

    def _sell(
        self,
        signal: Signal,
        close_price: float,
        held_quantity: int,
        config: BacktestConfig,
    ) -> TradeRecord:
        quantity = min(config.quantity_per_signal, held_quantity)
        price = close_price * (1.0 - config.slippage_rate)
        fees = price * quantity * config.transaction_cost_rate
        slippage = close_price * quantity * config.slippage_rate
        return TradeRecord(
            timestamp=signal.timestamp,
            symbol=signal.symbol,
            side=TradeSide.SELL,
            price=round(price, 6),
            quantity=quantity,
            fees=round(fees, 6),
            slippage=round(slippage, 6),
            reason=signal.reason,
        )

    def _holdings_value(
        self,
        holdings: dict[str, int],
        bars_by_key: dict[tuple[str, datetime], MarketBar],
        timestamp: datetime,
    ) -> float:
        value = 0.0
        for symbol, quantity in holdings.items():
            bar = bars_by_key.get((symbol, timestamp))
            if bar is not None:
                value += bar.close * quantity
        return value

    def _result_id(
        self,
        dataset: MarketDataset,
        signals: tuple[Signal, ...],
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
    ) -> str:
        payload = {
            "bars": [
                {
                    "symbol": bar.symbol,
                    "timestamp": bar.timestamp.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in dataset.bars
            ],
            "signals": [
                {
                    "symbol": signal.symbol,
                    "timestamp": signal.timestamp.isoformat(),
                    "signal_type": signal.signal_type.value,
                    "strength": signal.strength,
                    "reason": signal.reason,
                    "strategy_name": signal.strategy_name,
                }
                for signal in signals
            ],
            "strategy_config": strategy_config.to_dict(),
            "backtest_config": backtest_config.to_dict(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]
