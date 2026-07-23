# Market Data Operations

Run the fixture-backed market data demo:

```bash
python -m gaon.runtime.cli market-data-demo --db runtime.sqlite --symbol 005930
```

Run data quality:

```bash
python -m gaon.runtime.cli data-quality-demo --db runtime.sqlite --symbol 005930
```

Datasets are persisted in schema v32 table `market_datasets` with fingerprint,
checksum, provenance, and quality status.
