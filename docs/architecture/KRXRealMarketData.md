# KRX Real Market Data

Sprint 111 adds a public-data provider boundary for KRX-shaped daily market
data. The production `KRXRealMarketDataProvider` fails closed with
`real_data_unavailable` until an approved public fetcher is configured.

Automated tests and release checks use `KRXFixtureMarketDataProvider`, which is
explicitly marked `source=fixture` and `fixture_backed=true`. Fixture data is
never represented as real KRX data.

Tracked fields include symbol, trading date, OHLC, volume, trading value,
source metadata, fetched timestamp, and adjusted/raw status.
