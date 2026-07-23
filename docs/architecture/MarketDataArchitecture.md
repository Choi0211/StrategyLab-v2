# Market Data Architecture

Sprint 101-102 defines a common market data domain and provider boundary.

Core models:

- `MarketSymbol`
- `MarketBar`
- `MarketDataset`
- `MarketCalendar`
- `CorporateAction`
- `MarketDataMetadata`

Each dataset records source, market, timeframe, date range, adjusted flag,
retrieval time, and `fixture_backed`. The default provider is deterministic and
fixture-backed. Optional real providers must implement the provider interface
and preserve provenance instead of silently falling back.
