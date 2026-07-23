# Real Research Gateway

Sprint 110 connects market dataset resolution, data quality checks,
StrategySpec creation, external backtest adapter execution, result comparison,
self-critic, quality scoring, memory-ready report generation, and persistence.

The default implementation remains fixture-backed. Real data and real external
backtest engines can be connected later by implementing the provider and adapter
interfaces without adding private repository dependencies.

Safety boundaries:

- no live orders
- no automatic Champion promotion
- no automatic deployment
- no approval bypass
- no arbitrary shell
- no arbitrary SQL
- no generated Python strategy execution
