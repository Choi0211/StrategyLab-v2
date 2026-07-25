# Real Backtest Engine

Sprint 114 introduces a deterministic rule-based backtest engine for canonical
strategy primitives. It supports breakout entry, MA20/MA60 filters, volume MA20
confirmation, percentage stop, and channel-low exit.

The engine prevents look-ahead bias by calculating breakout highs, moving
averages, volume averages, and channel lows from prior bars only. It does not
execute LLM-generated Python and does not call a broker.

Execution assumptions are explicit: commission, tax, slippage, execution
timing, position sizing, and initial capital all carry provenance.
