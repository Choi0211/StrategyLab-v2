# Hotfix 140.6 Historical KRX Data Quality

## Purpose

Hotfix 140.6 separates KRX exchange-calendar closures from Yahoo KRX provider
anomalies before Sprint 141-150 starts.

## Findings

- `2023-05-29` is a KRX market closure and is excluded by `KRXTradingCalendar`.
- `2022-01-03` remains a KRX open trading day with a delayed market open.
- `2022-05-09` remains a KRX open trading day under the local calendar policy.
- `2025-09-19` remains a KRX open trading day and a Yahoo KRX provider gap.
- For `005930`, `2022-01-03` and `2022-05-09` are tracked as Yahoo symbol-specific provider gaps when absent from the provider payload.
- `2024-10-14` remains a Yahoo same-index OHLC anomaly for `005930`; the inconsistent bar is excluded and recorded as `provider_ohlc_anomaly`.

## Zero Volume Policy

Zero-volume bars are not automatically accepted. A zero-volume bar is blocking
unless it is explicitly registered as a dated provider anomaly with evidence.
Use the inspection CLI below to extract the exact dates and raw normalized
values from production Yahoo data.

## Commands

Deterministic release check:

```bash
python -m gaon.runtime.cli historical-krx-data-quality-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite
```

Production Yahoo inspection:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true \
GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli historical-krx-data-quality-inspect \
  --symbol 005930 \
  --start 2021-07-25 \
  --end 2026-07-24
```

Single-bar Yahoo parser diagnostic:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true \
GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli yahoo-krx-bar-debug \
  --symbol 005930 \
  --date 2024-10-14
```

## Safety

No live trading, KIS order, broker order, Champion auto-promotion, approval
bypass, arbitrary shell/SQL expansion, or schema migration is introduced.
