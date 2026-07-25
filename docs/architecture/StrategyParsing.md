# Strategy Parsing

Sprint 113 parses Korean natural-language strategy requests into a canonical
StrategySpec. The first supported strategy family is Turtle-style breakout:

- 20-day high breakout
- close > MA20 > MA60
- volume >= 20-day average
- protective stop -5%
- 10-day low channel exit

Each field records provenance. User-provided values are separated from defaults,
derived values, fixtures, and research candidates. Fixture-only metadata such as
`volume_multiplier`, `max_risk_pct`, and `regime_tags` is not copied into a user
strategy.
