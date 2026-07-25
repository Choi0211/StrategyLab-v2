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
- `unknown_missing_trading_day`: missing bar not explained by calendar or provider anomaly registry

Release checks allow `provider_gap` warnings only when no blocking findings are
present. Unknown missing trading days, malformed OHLCV, duplicate bars, and
errors remain blocking.
