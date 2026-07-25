# KRX Market Data Operations

Use fixture-backed checks locally:

```bash
python -m gaon.runtime.cli krx-real-research-release-check --db runtime.sqlite
```

Current production behavior:

- real provider boundary exists
- real public KRX fetcher can be enabled through Yahoo chart historical data
- unavailable real data reports `real_data_unavailable`
- fixture data remains explicitly marked `source=fixture`

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

Expected successful output includes `source=real`, `fixture_backed=false`,
`provider=real:yahoo-chart`, row count, and `quality=pass`.

Do not place credentials, private API clients, or broker connections in this
public repository.
