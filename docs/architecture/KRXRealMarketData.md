# KRX Real Market Data

Sprint 111 adds a public-data provider boundary for KRX-shaped daily market
data. The production `KRXRealMarketDataProvider` fails closed with
`real_data_unavailable` until an approved public fetcher is configured.

Automated tests and release checks use `KRXFixtureMarketDataProvider`, which is
explicitly marked `source=fixture` and `fixture_backed=true`. Fixture data is
never represented as real KRX data.

Real-data activation adds `YahooKRXHistoricalDataProvider`, a free public
historical OHLCV adapter for KRX-listed symbols through Yahoo's chart endpoint.
Examples:

- `005930` -> `005930.KS`
- `KQ:091990` -> `091990.KQ`

The provider records `source=real`, `provider=real:yahoo-chart`,
`fixture_backed=false`, retrieved timestamp, symbol, period, and row count. If
the provider fails, returns malformed data, or returns too few rows, the result
is `real_data_unavailable`; fixture data is not used as a fallback.

Tracked fields include symbol, trading date, OHLC, volume, trading value,
source metadata, fetched timestamp, and adjusted/raw status.
