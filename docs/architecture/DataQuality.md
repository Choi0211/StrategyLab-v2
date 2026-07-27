# Data Quality

Sprint 103 adds `DataQualityEngine`.

Checks:

- duplicate bars
- missing dates
- invalid OHLC
- negative volume
- zero or abnormal volume
- timestamp ordering
- symbol mismatch
- insufficient lookback
- stale data

Results are `pass`, `pass_with_warnings`, or `fail`. Failed datasets are not
sent to the real research backtest step.

## KRX Provider Gap Classification

KRX daily checks use the exchange trading calendar for expected bars. Exchange
closures are excluded by `KRXTradingCalendar`; provider-specific missing bars
must not be added as exchange holidays.

Missing trading dates can be classified as:

- `provider_gap`: known provider anomaly such as Yahoo KRX `2025-09-19`
- `provider_ohlc_anomaly`: provider returned an inconsistent same-index OHLC bar that is excluded without weakening OHLC validation
- `provider_zero_volume_anomaly`: provider-specific zero-volume anomaly only when a dated registry entry exists
- `unknown_missing_trading_day`: missing bar not explained by calendar or provider anomaly registry

`real:yahoo-chart` also has symbol-specific provider gaps for Samsung
Electronics (`005930`) on `2022-01-03` and `2022-05-09`. These dates remain KRX
open dates and are not exchange holidays. The substitute holiday `2023-05-29`
is modeled as a KRX closure.

Release checks allow only explainable provider anomaly warnings when no
blocking findings are present. Unknown missing trading days, unregistered
zero-volume bars, malformed OHLCV, duplicate bars, and errors remain blocking.
