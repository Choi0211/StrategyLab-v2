# Hotfix 185.5 - Production External Research Network Wiring

## Status

COMPLETE

## Problem

Production Telegram Autonomous Learning V2 used
`AutonomousExternalResearchExecutor()` without an explicitly configured
`BoundedSourceDiscoveryExecutor`. That constructor defaulted to
`NetworkExecutionPolicy(network_enabled=False)`, so the production route could
report `provider_failure` even when Crossref/DataCite connectivity was healthy.

## Design

- Production Telegram now builds a `BoundedSourceDiscoveryExecutor` with
  `NetworkExecutionPolicy(network_enabled=True)`.
- The API host allowlist remains limited to `api.crossref.org` and
  `api.datacite.org`.
- Discovery remains bounded by timeout, response byte, provider-call, and result
  budgets.
- Content acquisition remains separate and disabled by default for production
  Telegram. DOI/metadata locators are preserved as metadata only and are not
  treated as read source bodies.
- Metadata-only discovery results in `content_unavailable`, not
  `provider_failure`.
- Explicitly disabled discovery is surfaced as `discovery_network_disabled`.

## Safety

Metadata-only external research cannot generate claims or promotion candidates.
Production promotion remains blocked until real content-backed evidence and an
authoritative candidate backtest are available. No strategy mutation, order
execution, KIS/Broker call, Champion auto-promotion, or approval bypass was
added.

## Release Check

`gaon-production-external-research-network-release-check` uses a fake metadata
transport to prove the production wiring without live network access:

- discovery network explicitly enabled
- Crossref/DataCite allowlist preserved
- metadata discovery executed
- metadata-only evidence is not claimed as content
- `content_unavailable` is distinct from `provider_failure`
- fixture promotion remains blocked
- mutation/order safety remains false
