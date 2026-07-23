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
