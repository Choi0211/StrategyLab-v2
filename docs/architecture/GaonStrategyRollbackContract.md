# Gaon Strategy Rollback Contract

Status: PARTIAL (StrategyLab-v2 canonical read-model shipped; Binance
dashboard repository consumer change is a separate, follow-up PR in
`binance_ai_bot`)

## Problem

The Binance dashboard's `/api/strategy_params/backup_status` endpoint (in
the separate `binance_ai_bot` repository, not this one) currently reports
`available=false` whenever it cannot find a backup file on disk, and hides
the "roll back to previous strategy" button whenever that happens. This
makes the rollback feature look entirely absent from the web UI, and the
signal it uses (does a file exist) is not the same thing as "does a
genuine, restorable previous strategy version exist."

StrategyLab-v2 already has a canonical model for exactly this: ACTIVE /
PREVIOUS / APPLY_READY / RETIRED strategy versions
(`gaon.control.strategy_version.StrategyVersionRegistry`) and a read model
built on top of it for a strategy console UI
(`gaon.control.strategy_console.StrategyConsoleReadModel`). Both existed
before this change but had **no SQLite persistence and no HTTP wiring** -
pure in-memory dataclasses exercised only by unit tests (their own module
docstrings said so explicitly: "no production wiring, no deploy").

## What this PR ships (StrategyLab-v2 side)

1. **Durable persistence** for `StrategyVersionRegistry`, one registry per
   `family_id`, via a new additive `strategy_version_registries` table
   (schema v43, `gaon.runtime.migrations._upgrade_v42_to_v43`) and
   `gaon.runtime.strategy_version_repository.StrategyVersionSQLiteRepository`.
   The registry's own `to_json()`/`from_json()` round-trip is stored
   verbatim in one JSON column - no new column mapping for the free-form
   `spec_rules`/`validation_summary` fields.

2. **A read-only HTTP endpoint**: `GET /gaon/strategy/version_status?family_id=<id>`
   (`gaon.runtime.web_api`, wired the same way every other Gaon Web API
   route is - see `GaonWebChatAdapter.strategy_version_status`). Response
   shape:

   ```json
   {
     "schema_version": 1,
     "family_id": "binance-price-action",
     "active": { "strategy_version_id": "...", "status": "active", "spec_fingerprint": "...", "activated_at": "...", "...": "..." },
     "apply_ready": [ { "...": "a StrategyVersion.to_json()" } ],
     "previous": [ { "...": "a StrategyVersion.to_json()" } ],
     "retired": [ { "...": "a StrategyVersion.to_json()" } ],
     "actions": [ { "strategy_version_id": "...", "action": "rollback", "label": "Roll back to <fingerprint>" } ],
     "available_for_rollback": true,
     "strategy_mutated": false,
     "order_executed": false,
     "champion_promoted": false,
     "live_activated": false,
     "approval_bypassed": false
   }
   ```

   `available_for_rollback` is computed from the registry's own recorded
   `previous` entries (`len(previous) > 0`) - never from a file-existence
   check. With no versions ever registered for a family, or exactly one
   version that has only ever been ACTIVE (never superseded), it is
   truthfully `false`. It becomes `true` only once a **second** version
   has actually been activated, which is the same moment the registry
   demotes the first one to `PREVIOUS` (`StrategyVersionRegistry.mark_active`).
   `family_id` is a required query parameter - the endpoint never guesses
   which family/strategy a caller means (`400` if omitted).

   Root service discovery (`GET /`) advertises this route as
   `strategy_version_status`, alongside the existing routes, following the
   same convention as every other Gaon Web API endpoint.

3. **Tests**: `tests/unit/test_strategy_version_repository.py` (repository
   round-trip/isolation/idempotency), `tests/unit/test_strategy_version_status_api.py`
   (truthfulness of `available_for_rollback` across no-versions /
   single-ACTIVE-only / genuine-PREVIOUS / RETIRED-is-never-offered /
   cross-connection durability / family isolation / safety invariants /
   HTTP wiring).

## What this PR intentionally does NOT ship

- **No rollback ACTION endpoint** (no `POST` that calls
  `StrategyVersionRegistry.mark_active`/
  `gaon.control.strategy_deployment.StrategyDeploymentController.request_rollback`
  over HTTP). The control-layer rollback lifecycle already exists and is
  already tested (`tests/unit/test_strategy_deployment_lifecycle.py`,
  `src/gaon/control/strategy_deployment.py`) - rollback is documented there
  as "the SAME lifecycle [as apply] with a PREVIOUS version as the
  target," with the registry's ACTIVE pointer only moving on a verified
  commit. Exposing that over HTTP with real human-approval gating,
  audit/event recording, and rate limiting is real additional design work
  (an approval token, who is authorized to call it, how it is audited)
  that the task's explicit safety boundary ("rollback은 명시적 사용자
  승인/기존 safety boundary를 유지해야 하며 LIVE를 활성화하거나 주문을
  내면 안 됨") deserves a dedicated review of its own, not a rushed
  addition alongside the read-model work above. Nothing in this PR can
  mutate a strategy version, place an order, or touch LIVE mode - see the
  safety-invariant fields on every response.
- **No writer that populates real Binance strategy versions today.**
  `StrategyVersionRegistry`/`StrategyConsoleReadModel` remain, as before
  this PR, unconnected to `gaon.adapters.binance` (the existing read-only
  reader of the live Binance bot's actual `strategy_params.json`). Wiring
  "the Binance bot's own apply/rollback history" into this registry (so
  `GET /gaon/strategy/version_status?family_id=binance-price-action`
  reflects the REAL live bot, not just whatever StrategyLab's own future
  promotion workflow registers) is exactly the kind of two-repo
  integration work called out below.

## What the `binance_ai_bot` repository still needs to change

This cannot be done in this PR (per the task's constraint that a single
PR may only touch this repository). The Binance dashboard repository
needs a follow-up change:

1. Replace `/api/strategy_params/backup_status`'s file-existence check
   with either:
   - **(preferred)** a server-side call to this repository's
     `GET /gaon/strategy/version_status?family_id=<binance family id>`
     (over the existing Gaon Web API the dashboard already talks to for
     chat - see `docs/architecture/GaonBinanceConversationDashboardIntegration.md`),
     using the response's `available_for_rollback` field directly instead
     of `os.path.exists(...)`; or
   - if the Binance bot process needs to keep deciding this locally
     without a network call to StrategyLab-v2, mirror the SAME
     ACTIVE/PREVIOUS/APPLY_READY/RETIRED state machine
     (`gaon.control.strategy_version.StrategyVersionRegistry`'s lifecycle
     is small and dependency-free) against its own `strategy_params.json`
     history instead of a bare file-existence check, so "available" means
     "a verified, restorable previous version exists," not "some file is
     present on disk" (a stale, corrupt, or unrelated leftover file must
     not enable the button).
2. When the button IS shown and pressed, the actual rollback action
   (writing the previous `strategy_params.json` back, restarting/
   reloading the strategy) is owned entirely by the Binance repository's
   own deployment/rollback scripts (`deploy/scripts/rollback_service.sh`
   pattern, per `deploy/docs/vps_deployment_runbook.md`), gated by
   explicit human approval, and must never auto-enable LIVE mode or place
   an order as a side effect - the existing safety boundaries in that
   repository (already required to mirror this one's conventions per the
   runbook) apply unchanged.
3. If/when a StrategyLab-v2 promotion workflow should be the source of
   truth for Binance strategy versions specifically (rather than the bot
   process's own local history), that requires wiring
   `gaon.adapters.binance`'s existing read-only Binance state reader
   together with `StrategyVersionRegistry` - out of scope here, and
   deliberately not started in this PR to avoid touching Binance
   LIVE/order/approval-bypass/Champion-auto-promotion paths without a
   dedicated review.

## Safety

No live trading, KIS/Broker order, automatic Champion promotion, approval
bypass, strategy mutation, service restart, or production deployment is
added by this PR. `GET /gaon/strategy/version_status` is read-only; every
response carries `strategy_mutated: false`, `order_executed: false`,
`champion_promoted: false`, `live_activated: false`,
`approval_bypassed: false`, matching this codebase's existing convention
of making safety invariants machine-checkable fields, not just prose.
