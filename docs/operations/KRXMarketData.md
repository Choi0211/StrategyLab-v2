# KRX Market Data Operations

Use fixture-backed checks locally:

```bash
python -m gaon.runtime.cli krx-real-research-release-check --db runtime.sqlite
```

Current production behavior:

- real provider boundary exists
- real public KRX fetcher is not bundled
- unavailable real data reports `real_data_unavailable`
- fixture data remains explicitly marked `source=fixture`

Do not place credentials, private API clients, or broker connections in this
public repository.
