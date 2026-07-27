# KRX Market Data Operations

Use fixture-backed checks locally:

```bash
python -m gaon.runtime.cli krx-real-research-release-check --db runtime.sqlite
python -m gaon.runtime.cli krx-trading-calendar-release-check --db runtime.sqlite
python -m gaon.runtime.cli provider-gap-release-check --db runtime.sqlite
```

Current production behavior:

- real provider boundary exists
- real public KRX fetcher can be enabled through Yahoo chart historical data
- unavailable real data reports `real_data_unavailable`
- fixture data remains explicitly marked `source=fixture`
- daily KRX data quality is evaluated against trading dates, not raw calendar dates
- weekends and bounded deterministic KRX non-trading dates are not counted as missing bars
- malformed OHLCV, duplicate bars, stale data, and actual missing trading bars remain quality findings
- `2025-09-19` remains an exchange-open KRX date; for `real:yahoo-chart` it is classified as `provider_gap`, not as an exchange holiday
- `2022-01-03` and `2022-05-09` remain exchange-open dates; for `005930` only, they are classified as Yahoo provider gaps when absent from the provider payload
- `2023-05-29` is a KRX closure because it was the Buddha's Birthday substitute holiday
- registered `005930` Yahoo zero-volume anomaly bars are excluded from backtest input and disclosed as `provider_zero_volume_anomaly`
- unregistered zero-volume bars are not accepted as benign; inspect and classify them with dated evidence first
- `real-krx-data-release-check` allows provider-gap-only warnings while still blocking unknown missing trading days and malformed data

Production environment:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true
GAON_MARKET_DATA_PROVIDER=yahoo-chart
GAON_MARKET_DATA_TIMEOUT_SECONDS=20
```

Production live-data check:

```bash
python -m gaon.runtime.cli real-krx-data-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite \
  --symbol 005930 \
  --start 2025-01-01 \
  --end 2026-07-24
```

Historical quality investigation:

```bash
python -m gaon.runtime.cli historical-krx-data-quality-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite

GAON_REAL_MARKET_DATA_ENABLED=true \
GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli historical-krx-data-quality-inspect \
  --symbol 005930 \
  --start 2021-07-25 \
  --end 2026-07-24
```

Expected successful output includes `source=real`, `fixture_backed=false`,
`provider=real:yahoo-chart`, row count, `provider_gaps`, `blocking_findings`,
and either `quality=pass` or provider-gap-only `quality=pass_with_warnings`.

Do not place credentials, private API clients, or broker connections in this
public repository.
