# Unified Dashboard Storage Filesystem Dedup

Status: Implemented

## Context

The unified mobile dashboard showed `/opt/strategylab-v2` and
`/var/lib/strategylab` as separate `10GB / 23GB` storage capacity cards.
Those numbers come from filesystem capacity, not from each directory's own
byte usage.

## Root Cause

`deploy/scripts/storage_lifecycle_manager.py` documented distinct-filesystem
de-duplication, but `_disk_usage_for()` keyed entries by `Path.resolve()`.
Two different roots on the same VPS filesystem therefore produced two
capacity records with identical total/used/free values.

## Design

The storage report now separates:

- `tier_bytes` and `file_counts`: directory data classified as HOT/WARM/COLD.
- `disk_usage`: filesystem capacity, de-duplicated by device identity.
- `filesystem_usage`: additive dashboard-friendly list of the same
  de-duplicated filesystem capacity entries.

Each filesystem entry preserves all configured roots in `paths[]` and the
actual probed paths in `probed_paths[]`, so the dashboard can render one
capacity card with included root paths instead of double-counting.

## Safety

The report path remains read-only. No cleanup, migration, trading action,
order path, Champion promotion, approval bypass, or strategy mutation is
introduced.

## Limitations

This change fixes the StrategyLab-owned storage status backend and Gaon web
storage API contract. The separate private `binance_ai_bot` dashboard
repository must consume the new `filesystem_usage` shape to complete the
mobile UI simplification.
