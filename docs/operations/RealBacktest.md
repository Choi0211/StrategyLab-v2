# Real Backtest Operations

Release checks:

```bash
python -m gaon.runtime.cli strategy-parser-release-check --db runtime.sqlite
python -m gaon.runtime.cli real-backtest-release-check --db runtime.sqlite
```

The rule engine supports only approved StrategySpec primitives. It applies
commission, tax, slippage, execution timing, position sizing, and initial
capital assumptions explicitly.

Results are research artifacts only. They are not trading instructions.
