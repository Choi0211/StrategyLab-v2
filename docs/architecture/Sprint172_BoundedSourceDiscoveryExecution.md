# Sprint 172 — Bounded Source Discovery Execution

Status: IMPLEMENTED

## Goal

Execute Sprint 171 Source Discovery Plans against bounded real research
metadata providers.

Sprint 172 is the first Knowledge Acquisition sprint that contains an
actual network-capable provider implementation.

## Initial Providers

### Crossref

Purpose:

- academic papers
- research reports

Endpoint:

`https://api.crossref.org/works`

The executor uses bounded bibliographic queries.

### DataCite

Purpose:

- datasets

Endpoint:

`https://api.datacite.org/dois`

The executor restricts DataCite discovery to dataset resources.

## Explicitly Not Implemented Yet

`OFFICIAL_WEB`

The provider remains fail-closed until a safe official-domain discovery
strategy is implemented.

`GENERAL_WEB`

Not enabled.

There is no arbitrary search-engine or web-crawler execution in Sprint 172.

## Network Safety

Network access is disabled by default.

`NetworkExecutionPolicy.network_enabled` must be explicitly true.

Outbound provider HTTP requests require:

- HTTPS
- host allowlist
- standard HTTPS port
- no URL userinfo
- same-host redirects only
- timeout
- response-byte limit

Initial API allowlist:

- api.crossref.org
- api.datacite.org

## Research Budgets

Sprint 171 limits remain authoritative:

- maximum query count
- maximum results per query
- maximum total results

Sprint 172 cannot exceed them.

## Result Trust Boundary

A discovered result is not knowledge.

Every discovery result remains:

- provenance_created=false
- ingested=false
- quality_evaluated=false
- knowledge_validated=false
- production_approved=false

Sprint 172 does not download the discovered paper, report, or dataset body.

A future ingestion sprint must explicitly move the result through:

Discovery Result
→ Provenance
→ Raw Evidence
→ Source Quality Gate
→ Claim Extraction
→ Knowledge Candidate
→ Conflict Re-evaluation

## Failure Policy

Failures are classified and fail closed:

- network disabled
- unsupported provider
- blocked host
- invalid provider response
- HTTP error
- timeout
- network error
- budget exhausted

A failure on one discovery query does not fabricate a result.

## Safety

Sprint 172 cannot:

- auto-ingest discovered sources
- auto-validate knowledge
- mutate a research strategy
- mutate production config
- promote Champion
- activate KIS/Broker trading
- place live orders

## Live Smoke Test

Live provider access is intentionally excluded from deterministic unit and
release tests.

After deployment it can be manually checked using:

`python -m gaon.knowledge.execution live-smoke --provider crossref --query "trend following market regimes" --limit 3`

or:

`python -m gaon.knowledge.execution live-smoke --provider datacite --query "financial market regime" --limit 3`

Optional environment:

`GAON_DISCOVERY_CONTACT=you@example.com`

This allows Crossref requests to identify the integration.
