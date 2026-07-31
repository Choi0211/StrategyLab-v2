# Hotfix 152.3 Result Units and Presentation Integrity

Status: COMPLETE

## Context

Sprint 152 made Gaon answer Telegram research requests with deterministic Korean
summaries. Hotfix 152.3 tightens the presentation contract so user-facing
research responses preserve metric units, hide internal identifiers, and avoid
raw provenance strings in normal conversational output.

## Root Cause

`RealPerformanceMetrics.expectancy` is calculated from realized trade PnL:

```text
expectancy = win_rate * average_win + (1 - win_rate) * average_loss
```

It is therefore a capital-denominated amount, not a percentage. The previous
detail renderer formatted expectancy through the generic percent formatter,
which could turn `297134.3` into a fabricated-looking `29713430.00%`.

The same renderer also exposed implementation details such as strategy
fingerprints, raw quality status keys, and raw data-source values. Those fields
remain valid internal evidence, but they are not appropriate as default
Telegram-facing text.

## Metric Semantics

- `total_return`, `cagr`, `mdd`, `win_rate`, and `exposure` are decimal ratios
  and are rendered as percentages.
- `average_trade`, `average_win`, `average_loss`, `expectancy`,
  `ending_equity`, and `initial_capital` are capital-denominated amounts and
  are rendered as numeric money-like values without silently converting units.
- `trade_count` and `longest_losing_streak` are counts.
- `sharpe`, `profit_factor`, and `payoff_ratio` are dimensionless ratios.
- Missing or zero-trade metrics are rendered as unavailable or not calculable;
  they are not converted into reassuring zero-risk statements.

## Fingerprint Audit

`CanonicalStrategySpec.fingerprint` includes fields from the full strategy spec,
including the symbol and creation timestamp. It is useful for internal lineage,
but it is not a pure user strategy-configuration fingerprint and must not be
shown by default as proof that two runs used identical strategy assumptions.

## Presentation Contract

Default Korean Telegram and conversational MVP responses:

- hide `strategy_fingerprint`, `run_id`, validation IDs, raw schema class names,
  and internal candidate IDs;
- replace raw `quality_status=pass` with Korean data-quality wording;
- replace `source=real:yahoo-chart` with `데이터 출처: Yahoo Chart 공개 데이터`;
- deduplicate repeated warning prefixes such as `주의: 주의:`;
- describe outcomes as observed backtest results, not guaranteed or stable
  strategy performance.

## Release Check

`gaon-result-presentation-release-check` verifies that expectancy keeps currency
units, optional capital-relative percent is clearly derived, internal IDs remain
hidden, raw provenance keys are not exposed, and warnings are deduplicated.

## Safety

No schema migration is included. This hotfix does not change trading behavior,
research calculations, market data quality gates, approval rules, Champion
promotion, or strategy configuration mutation.
