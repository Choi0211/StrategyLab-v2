# Market Data Contract

Status: Sprint 2 Foundation

## Required OHLCV Fields

Every market bar must provide:

- `symbol`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

## Dataset Requirements

A valid official dataset must:

- contain at least one bar
- have no missing required values
- have no duplicate `(symbol, timestamp)` keys
- have `high >= low`
- have non-negative volume
- match the expected symbol universe when one is provided
- stay within the requested date range when one is provided

## Provenance Requirements

Every dataset must record:

- source name
- collection timestamp
- frequency
- timezone
- symbol universe
- start date
- end date
- preprocessing steps

## Public Repository Safety

The public StrategyLab-v2 repository may contain:

- synthetic fixtures
- public sample data
- schemas
- validation tests

The public repository must not contain:

- real account data
- broker credentials
- API tokens
- private MyMoneyGuard files
- production logs
- private market data dumps

## Sprint 2 Fixture Policy

Sprint 2 uses synthetic in-memory fixtures only. This keeps validation behavior reproducible and independent from network access, broker APIs, or vendor data.

