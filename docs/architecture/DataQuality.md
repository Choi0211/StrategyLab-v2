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

`real:yahoo-chart` also has symbol-specific provider gaps for the Sprint
141-150 research universe. `2022-01-03` and `2022-05-09` are classified for
`005930`, `000660`, `005380`, `035420`, and `051910`; `000660` additionally has
`2023-02-02` and `2023-02-09`, `005380` has `2023-02-01`, and `035420` has
`2023-02-02`. These dates remain KRX open dates and are not exchange holidays.
The substitute holiday `2023-05-29` is modeled as a KRX closure.

Yahoo zero-volume anomalies are registered only for dated production findings
where Yahoo returned `volume=0`, `trading_value=0`, and `open=high=low=close`.
The registered Sprint 141-150 symbols are `005930`, `000660`, `005380`,
`035420`, and `051910`; each symbol keeps a dated evidence set made from the
common 2022 Yahoo zero-volume anomaly dates plus any symbol-specific additional
dates from production inspection. Registered zero-volume anomaly bars are
excluded from backtest input and reported as
`provider_zero_volume_anomaly`. Any unregistered zero-volume bar remains
blocking.

Yahoo anomaly lookup canonicalizes suffix forms such as `.KS` and `.KQ` before
registry matching, so production inspection and test paths use the same
provider anomaly registry.

Release checks allow only explainable provider anomaly warnings when no
blocking findings are present. Unknown missing trading days, unregistered
zero-volume bars, malformed OHLCV, duplicate bars, and errors remain blocking.
