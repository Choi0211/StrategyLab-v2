# Gaon V2 Final Closeout

Status: IN PROGRESS  
Branch: `feature/gaon-v2-production-completion`  
Schema: v36 unchanged

## Purpose

This is the final production closeout audit for Gaon V2. It is not a new
research Sprint. The audit verifies that the existing Autonomous Quant Partner,
Telegram conversation layer, real-data validation, approval gates, Champion
registry, rollback, and safety boundaries compose into one production-safe
operating contract.

## Audit Matrix

- `already_complete`: real/fixture provenance, KRX/Yahoo data quality gates,
  provider anomaly isolation, bounded source acquisition, metadata-only evidence
  blocking, counter-evidence records, candidate fingerprint checks, real
  validation gates, tournament ranking, human promotion gate, Champion registry,
  Champion version history, rollback, Telegram authoritative context routing,
  and machine-checkable safety fields.
- `partially_complete`: production provider categories that honestly report
  unavailable or not configured state when no live provider is configured.
- `wired_but_not_live`: external source categories whose contracts are present
  but whose production credentials or endpoints may be unavailable on a given
  VPS. They must not be treated as supporting evidence when unavailable.
- `missing`: none for the deterministic final closeout contract after this
  audit. Live Telegram/VPS acceptance remains an operational verification step.
- `not_applicable`: live trading, KIS/Broker orders, automatic Champion
  promotion, and approval bypass remain out of scope and disabled.

## Durable Approval And Champion Lifecycle

The final closeout release check uses a temporary SQLite database, closes and
reopens it at each lifecycle boundary, and verifies persisted state rather than
only in-memory objects.

Covered lifecycle:

1. Stage 1 human approval freezes an immutable candidate snapshot.
2. Frozen snapshot stores candidate ID, candidate fingerprint, source,
   fixture flag, validation ID, evidence ID, approval ID, and snapshot hash.
3. Duplicate Stage 1 replay is blocked by append-only durable event identity.
4. Restart after Stage 1 recovers the frozen candidate snapshot.
5. Material candidate fingerprint changes invalidate the Stage 1 snapshot.
6. Stage 2 Champion approval request must point at the frozen candidate
   fingerprint.
7. Restart after Stage 2 request recovers the pending approval.
8. Champion replacement activates only after Stage 2 approval.
9. Duplicate Stage 2 approval replay is idempotent and cannot create another
   Champion history revision.
10. Processed approval cannot be reused for a different promotion request.
11. Simulated mid-replacement failure rolls back and preserves the old Champion.
12. Restart after activation recovers the active Challenger.
13. Rollback restores the previous Champion, records reason/timestamp, retains
   promotion and Champion history, and survives restart.

## Market Data Freshness And Lineage

The final closeout payload exposes market-data lineage fields:

- symbol
- source
- fixture_backed
- requested_start/requested_end
- actual_start/actual_end
- raw_bars/usable_bars/warmup_bars
- window_fingerprint
- last_market_timestamp
- retrieval timestamp marker
- stale flag

Release-validation data uses deterministic validation inputs and declares
`check_mode=deterministic_release_validation`; it must not be presented as live
Yahoo evidence.

## Provider Readiness

Provider readiness is reported as a matrix. Provider categories that are not
configured must remain honest `provider_not_configured` style states. Production
must not silently substitute fixture adapters, unbounded network fetches, or
metadata-only evidence for promotion readiness.

## Telegram And Conversation

The final closeout checks that the normal Telegram-facing policy remains Korean
for Korean requests and that raw/debug fields are separate from normal
user-facing rendering. Presentation or explanation layers may re-render
authoritative context but must not mutate structured facts.

## Final Release Check

Aggregate command:

```bash
python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check
python -m gaon.runtime.cli gaon-production-v1-v2-final-integration-release-check
```

Focused commands remain available:

```bash
python -m gaon.runtime.cli gaon-production-final-autonomous-research-release-check
python -m gaon.runtime.cli gaon-production-final-conversation-release-check
python -m gaon.runtime.cli gaon-production-two-stage-approval-release-check
python -m gaon.runtime.cli gaon-production-candidate-freeze-release-check
python -m gaon.runtime.cli gaon-production-champion-replacement-release-check
python -m gaon.runtime.cli gaon-production-champion-rollback-release-check
python -m gaon.runtime.cli gaon-production-final-safety-boundary-release-check
python -m gaon.runtime.cli gaon-production-gaon-v2-completion-release-check
python -m gaon.runtime.cli gaon-production-v1-asset-reuse-audit-release-check
python -m gaon.runtime.cli gaon-production-v1-v2-authoritative-path-release-check
python -m gaon.runtime.cli gaon-production-no-unintended-duplicate-engine-release-check
python -m gaon.runtime.cli gaon-production-research-memory-continuity-release-check
python -m gaon.runtime.cli gaon-production-legacy-path-isolation-release-check
```

The V1/V2 integration audit verdict is `GAON V1/V2 INTEGRATION COMPLETE`.
It verifies that public V1 assets were reused or intentionally replaced, that
private MyMoneyGuard/KIS runtime assets remain excluded, and that no unintended
duplicate production engine is on the authoritative Telegram research path.

## Safety Invariants

- No live trading.
- No KIS/Broker order.
- No automatic Champion promotion.
- No approval bypass.
- No strategy mutation without explicit approved configuration flow.
- No fixture-backed production promotion.
- No metadata-only promotion evidence.
- No fabricated evidence or metrics.
- Data quality remains fail-closed for unregistered anomalies.

## Operational Verification

VPS closeout verification:

```bash
cd /opt/strategylab-v2
git pull origin main
.venv/bin/pip install -e .
systemctl restart strategylab-gaon
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon
.venv/bin/python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Telegram production acceptance should verify that a real autonomous research
request either reaches human approval readiness with all gates satisfied or
returns honest blockers without applying any strategy change.

## Rollback

Code rollback follows normal Git deployment rollback. Champion rollback uses
the existing Champion registry history and the explicit rollback command. The
final closeout check verifies that approval, Champion history, rollback reason,
and rollback timestamp remain auditable after restart.
