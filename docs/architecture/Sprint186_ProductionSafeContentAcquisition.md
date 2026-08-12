# Sprint 186 - Production Safe Content Acquisition

Status: COMPLETE

## Context

Hotfix 185.5 enabled bounded production metadata discovery for Telegram
Autonomous Learning V2. Discovery was intentionally metadata-only, so
`content_unavailable` remained the main blocker for evidence-backed claims,
hypotheses, ranking, and promotion review.

## Goal

Sprint 186 connects the existing bounded source content acquisition,
normalization, and claim bridge components to the production Telegram
Autonomous Learning V2 external research path.

## Design

Production execution now runs:

1. Crossref/DataCite bounded metadata discovery.
2. Explicit allowlisted content acquisition.
3. Safe content normalization.
4. Verbatim claim extraction.
5. Evidence reevaluation.
6. Existing hypothesis, real backtest validation, ranking, and promotion gate.

Downloaded content is stored and processed only as inert DATA. Source content is
never executed as code, instruction, script, macro, shell, SQL, or trading
action.

## Network Controls

Content acquisition is bounded by:

- explicit content host allowlist
- HTTPS-only URLs
- no URL credentials
- no non-standard HTTPS port
- private/loopback/link-local destination blocking
- same-host redirects only
- redirect count limit
- timeout
- maximum response bytes
- MIME allowlist
- provider/source budget

The default production content allowlist is intentionally narrow and can be
overridden through `GAON_EXTERNAL_RESEARCH_CONTENT_ALLOWED_HOSTS`.

## Acquisition States

The structured payload distinguishes:

- `content_acquired`
- `content_unavailable`
- `content_blocked`
- `unsupported_content_type`
- `fetch_failure`
- `metadata_only`

Metadata-only results cannot create claims, validated knowledge, promotion
evidence, or human approval requests.

## Observability

Telegram structured payloads now expose:

- discovery source and locators
- content acquisition state
- content URL and final URL
- MIME/content type
- byte count
- content SHA-256
- source ID
- normalized source IDs
- blocked reasons

## Safety

Sprint 186 preserves:

- no live trading
- no KIS/Broker order
- no Champion auto-promotion
- no approval bypass
- no strategy mutation
- no fixture-backed promotion
- no fabricated evidence or metrics
- fail-closed behavior for unsupported, blocked, failed, or metadata-only
  external research content

Schema remains v36.
