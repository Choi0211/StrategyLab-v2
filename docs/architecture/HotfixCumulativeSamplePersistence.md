# Hotfix: Cumulative Sample Persistence

Status: IMPLEMENTED

## Context

Production mission continuation showed one canonical strategy candidate
regressing from `5 symbols / 40 trades` to `10 symbols / 57 trades`, then
back to `5 symbols / 30 trades` after a later EXPAND_SAMPLE cycle. The
candidate fingerprint stayed constant, so this was not a strategy rotation.

## Root Cause

`StrategyCandidateRecord.record_breadth_progress()` persisted the latest
multi-symbol batch summary directly into `attempted_symbols`,
`valid_symbols`, and `trade_count`. The presentation layer then read those
persisted scalar fields. This made the defect a real mission-state
persistence bug, not only a renderer bug.

The older `evidence_symbols` list was also bounded to a short display list,
so it could not safely serve as the canonical evidence identity for
cumulative sample accounting.

## Design

Breadth evidence is now stored as a canonical symbol-keyed evidence map on
`StrategyCandidateRecord`:

- one logical symbol contributes at most one breadth evidence record;
- duplicate replay of the same symbol does not double count trades;
- distinct new symbols accumulate into the same candidate fingerprint;
- legacy records preserve their already persisted aggregate trade count as
  `breadth_legacy_trade_count`, so restart cannot regress old production
  state.

The legacy scalar fields remain part of the public record/read model, but
for new breadth evidence they are derived from the canonical map.

## Runtime Wiring

Telegram mission-driven breadth execution now passes per-symbol evidence
details from the existing `multi_symbol_research` output into
`record_breadth_progress()`. The details include symbol, eligibility,
metrics trade count, evidence id, quality status, source, and
`fixture_backed` provenance.

## Invariants

- Candidate fingerprint and strategy spec remain unchanged.
- Candidate history is never deleted or overwritten.
- Batch-local summaries stay separate from cumulative candidate state.
- No fabricated metrics are introduced.
- No live trading, broker/KIS order, Champion auto-promotion, approval
  bypass, or unapproved strategy mutation is added.
- Schema remains v36.

## Release Check

`gaon-production-cumulative-sample-persistence-release-check` proves:

- first batch `5 / 40` is recorded;
- second batch accumulates to `10 / 57`;
- later local batch `5 / 30` produces canonical `15 / 87`, not regression;
- duplicate replay does not double count;
- restart preserves cumulative state;
- legacy restart keeps the persisted aggregate floor.
