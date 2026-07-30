# Sprint 151 Dynamic KRX Universe Selection

## Status

COMPLETE

## Context

Sprint 141-150 introduced bounded multi-symbol KRX research with explicit or
curated symbol lists. Hotfix 150.1 through 150.5 then hardened Telegram routing,
Yahoo KRX anomaly classification, symbol canonicalization, and VPS deployment
import-path verification.

The remaining limitation is that Gaon cannot yet derive a research universe
from market data. Users must supply every symbol manually, or the system falls
back to the fixed five-symbol research universe.

## Problem

Manual symbol entry does not scale. However, automatically selecting symbols is
dangerous unless the selected universe is deterministic, source-backed,
auditable, and separated from approval or trading workflows.

## Goal

Add a read-only dynamic KRX universe selector that can rank eligible symbols by
trading value and pass the resulting canonical symbols into the existing
multi-symbol research pipeline.

## Non-goals

- Portfolio-level backtest or capital allocation.
- Symbol weight optimization.
- Live trading, KIS orders, broker orders, or Telegram configuration mutation.
- Automatic Champion promotion.
- Automatic strategy parameter changes.
- Unapproved universe application to a production strategy.
- New external market-data provider integration.
- Guess-based ETF, ETN, SPAC, preferred-share, or management-issue detection.

## User Scenarios

- Select the top 20 KRX symbols by trading value for a given date.
- Exclude one or more user-specified symbols before selection.
- Inspect the deterministic ranking and exclusion reasons.
- Run multi-symbol research from an approved universe result while preserving
  explicit-symbol precedence.

## Domain Model

- `KRXUniverseRequest`
- `KRXUniverseEntry`
- `KRXUniverseExclusion`
- `KRXUniversePolicy`
- `KRXUniverseResult`

All models are immutable dataclasses. They validate market, date, metric, size,
canonical six-digit KRX symbols, source, fixture provenance, and deterministic
serialization at construction time.

## Universe Selection Contract

Inputs:

- `market`: `KOSPI`, `KOSDAQ`, or `ALL`
- `selection_date`: date-only string
- `ranking_metric`: currently `trading_value`
- `requested_size`: positive integer
- `exclusions`: optional symbols to exclude
- `minimum_trading_value`: optional lower bound
- `minimum_volume`: optional lower bound

Outputs:

- `universe_id`
- request configuration
- selected canonical symbols
- ranked entries
- exclusion summary
- data-quality summary
- warnings
- deterministic policy snapshot

## Data Sources

Sprint 151 uses only market-data providers already available in StrategyLab v2.
The release check uses a deterministic fixture provider and does not require
network access.

Real KRX/Yahoo production validation remains a separate operational check. If a
provider cannot supply the requested universe snapshot, selection fails closed.

## Ranking Rules

- Sort by `trading_value` descending.
- Break ties by canonical six-digit KRX symbol ascending.
- Results are deterministic for the same input and provider snapshot.

## Filtering Rules

- Reject invalid market, invalid date, invalid metric, and non-positive size.
- Exclude symbols that cannot be canonicalized to six-digit KRX codes.
- Exclude duplicate symbols after canonicalization.
- Exclude user-specified symbols.
- Exclude rows with volume equal to zero.
- Exclude rows with trading value less than or equal to zero.
- Apply optional minimum volume and trading-value thresholds.

ETF, ETN, SPAC, preferred-share, and management-issue filtering is only
implemented when reliable source metadata is available. Guess-based filtering
is out of scope.

## Determinism

The same request and provider snapshot must produce the same `universe_id`,
symbol order, ranked entries, warnings, and JSON payload.

## Data-Quality Rules

The selector preserves existing data-quality policy:

- fixture and real provenance are explicit
- `source` is explicit
- `fixture_backed` is explicit
- partial provider data cannot be silently treated as complete
- stale cached data cannot be treated as fresh live data
- unknown missing trading dates remain blocking in downstream research
- provider anomaly registry behavior remains unchanged

## Fail-Closed Behavior

Selection fails closed when:

- market is unsupported
- selection date is not a valid KRX trading date
- provider universe data is unavailable
- provider returns no eligible rows
- canonical symbol conversion fails for all rows
- provider errors occur

If fewer than the requested size is selected, the result succeeds only with an
explicit warning and `selected_size < requested_size`.

## CLI/API Surface

New CLI:

```bash
python -m gaon.runtime.cli krx-universe-select \
  --market ALL \
  --date 2026-07-30 \
  --metric trading_value \
  --size 20
```

Options:

- `--market`
- `--date`
- `--metric`
- `--size`
- `--exclude`
- `--json`

Release check:

```bash
python -m gaon.runtime.cli krx-universe-release-check
```

The release check uses deterministic fixture data and must not require network
access.

## Persistence And Auditability

Sprint 151 does not add a new database schema. Universe results are auditable
through deterministic JSON payloads and through the existing multi-symbol
universe snapshot when a result is passed into multi-symbol research.

If durable universe catalogs are needed later, they must be added in a separate
sprint with explicit schema and migration review.

## Acceptance Criteria

- Trading-value ranking is deterministic.
- Ties are resolved by canonical symbol.
- Invalid requests fail closed.
- Zero-volume and zero-trading-value rows are excluded.
- Duplicate and excluded symbols are removed.
- Fixture and real provenance are explicit.
- CLI table and JSON output work.
- `krx-universe-release-check` passes without network access.
- Existing explicit multi-symbol requests keep priority over automatic
  universe selection.
- Multi-symbol research can accept a universe result as input without changing
  existing explicit-symbol behavior.

## Test Matrix

- Unit: ranking, tie-break, validation, exclusion, duplicate handling,
  canonicalization, insufficient results, provider failure, deterministic JSON.
- Integration: CLI JSON output, release check, universe-to-multi-symbol
  research connection, existing multi-symbol explicit request regression.
- Regression: historical KRX data quality, provider anomaly registry,
  deployment import-path check.

## Operational Verification

Local deterministic:

```bash
python -m gaon.runtime.cli krx-universe-release-check
python -m gaon.runtime.cli krx-universe-select --market ALL --date 2026-07-30 --metric trading_value --size 5 --json
python -m gaon.runtime.cli deployment-import-path-check
```

Production real-data validation is pending until an approved provider can supply
real KRX universe snapshots.

## Rollback

Rollback is code-only because no schema migration is included. Revert the Sprint
151 commits and restart the runtime service after editable reinstall.

## Documentation

Update:

- `README.md`
- `docs/releases/CHANGELOG.md`
- `docs/releases/ReleaseNotes.md`
- `docs/tests/TestResults.md`
- `docs/operations/KRXMarketData.md` if operational commands change

## Completion Checklist

- [x] Brief accepted in branch
- [x] Domain model implemented
- [x] CLI implemented
- [x] Multi-symbol connection implemented
- [x] Unit tests pass
- [x] Integration tests pass
- [x] Release verification passes
- [x] Documentation updated
- [ ] Production real-universe provider verification
- [ ] Working tree clean after commit
