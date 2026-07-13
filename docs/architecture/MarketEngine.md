# Market Engine

Status: Sprint 2 Foundation

## Purpose

The Market Engine provides validated market datasets for later strategy, backtest, portfolio, risk, and AI research workflows.

Sprint 2 implements only the public, testable foundation:

- data models
- provenance records
- validation rules
- adapter boundary
- in-memory adapter
- cache interface

It does not connect to live market data, broker APIs, paid vendors, or private MyMoneyGuard files.

## Core Contracts

### MarketBar

`MarketBar` represents one OHLCV record:

- `symbol`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

### MarketDataset

`MarketDataset` contains a tuple of `MarketBar` records and one `DataProvenance` record.

It exposes:

- `symbols`
- `start_date`
- `end_date`
- `filter(symbol, start, end)`

### DataProvenance

`DataProvenance` records:

- source metadata
- symbol universe
- start date
- end date
- preprocessing steps

### DataSourceMetadata

`DataSourceMetadata` records:

- source name
- collection timestamp
- frequency
- timezone

## Validation Rules

`MarketDataValidator` checks:

- empty datasets
- missing required values
- duplicate `(symbol, timestamp)` keys
- invalid OHLC ranges
- negative volume
- symbol universe mismatch
- requested date range mismatch

## Adapter Boundary

`MarketDataAdapter` defines the loading interface:

```python
load(symbols, start=None, end=None)
```

`InMemoryMarketDataAdapter` is the Sprint 2 test implementation. Real data providers are explicitly out of scope.

## Cache Boundary

`MarketDataCache` defines a minimal `get` / `set` interface. Concrete cache behavior is not implemented in Sprint 2.

## Non-Goals

Sprint 2 does not implement:

- KIS API
- Kiwoom API
- IBKR API
- Alpaca API
- paid vendor integration
- live downloads
- strategy signals
- backtest execution
- portfolio accounting

