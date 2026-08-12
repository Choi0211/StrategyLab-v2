# Hotfix 192.1 - Real Academic Content Resolution

Status: COMPLETE

## Root Cause

Sprint 186 proved safe content acquisition with deterministic direct content
URLs, but production Crossref/DataCite results often start as DOI or academic
metadata locators. The production bridge did not preserve DOI/resource metadata
or expose a dedicated safe academic resolution step, so real Telegram
Autonomous Learning V2 could discover metadata and still end at
`content_unavailable`.

## Design

Hotfix 192.1 adds a dedicated academic content resolution step before bounded
content acquisition.

Supported locator forms:

- Direct HTTPS content locator.
- Raw DOI such as `10.xxxx/...`.
- DOI URL such as `https://doi.org/10.xxxx/...`.
- Safe metadata resource URLs supplied by Crossref/DataCite metadata.

Resolution outcomes remain explicit:

- `direct_content_url`
- `doi_resolved`
- `metadata_resource_url`
- `content_unavailable`
- `content_blocked`
- `resolution_failure`

Metadata-only DOI/title records still cannot become grounded evidence.

## Safety

- HTTPS only.
- URL credentials blocked.
- Non-standard HTTPS ports blocked.
- Loopback/private/link-local destinations blocked by the production transport.
- Content host allowlist preserved.
- MIME, timeout, redirect, provider-call, source-count, and byte budgets remain enforced.
- DOI redirects are resolved only inside the dedicated academic resolver path.
- A DOI redirect or metadata resource to an unauthorized host is `content_blocked`.
- Downloaded content remains inert DATA and is never executed.

## Observability

External research payloads now include `resolution_records` and compact
observability fields for:

- provider
- result ID
- title
- original locator
- locator kind
- DOI
- resolution attempted
- resolution status
- resolved content URL
- final host
- redirect chain
- acquisition status
- failure kind
- content type
- byte count
- content SHA-256

## Release Check

New command:

```bash
python -m gaon.runtime.cli gaon-production-real-academic-content-resolution-release-check
```

The positive path starts from Crossref-style DOI metadata, resolves to an
allowlisted content URL, acquires content, normalizes it, extracts bounded
claims, creates grounded evidence, and feeds the existing Sprint 187-192
production loop.

The same check also proves fail-closed paths for metadata-only results,
unauthorized publisher hosts, HTTP targets, unsupported MIME, oversized content,
timeout/fetch failure, fixture-backed evidence, and candidate fingerprint
mismatch.

## Schema

Schema v36 preserved. No migration.
