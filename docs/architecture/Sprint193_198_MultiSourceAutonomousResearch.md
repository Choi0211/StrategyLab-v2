# Sprint 193-198 - Multi-Source Autonomous Research

Status: Implemented

## Context

Autonomous Learning V2 previously depended on academic discovery and content
acquisition as the only external evidence path. Production must now model a
bounded multi-source research loop without allowing arbitrary crawling,
fixture-backed promotion evidence, or fabricated metrics.

## Scope

Sprint 193-198 adds a unified multi-source research contract for these source
categories:

- academic
- official_market
- corporate
- regulatory
- news
- professional_research
- web
- youtube
- community
- social

Each provider reports discovery, acquisition, claim extraction, provenance,
credibility tier, independence key, contradiction state, and safety flags using
the shared `MultiSourceResearchOrchestrator` contract.

## Production Contract

Production Telegram still starts from authoritative real KRX/Yahoo baseline
research. Multi-source research is attached as structured context under
`autonomous_learning_v2.multi_source_research`.

Production adapters that are not explicitly configured return `not_configured`.
They do not fabricate claims, content, ranking, promotion candidates, orders,
or configuration mutations.

Acquired content can become evidence only when it has:

- non-fixture provenance
- acquisition state `content_acquired` or `transcript_acquired`
- content hash
- source ID
- claim text derived from acquired content

Metadata-only records cannot create claims or promotion evidence.

## Evidence Intelligence

The evidence fusion layer deduplicates normalized claims, counts independent
sources, records credibility distribution, and marks conflict state as
supporting, contradicting, mixed, or insufficient.

Community, social, and YouTube material is exploratory by default. Reposts or
duplicate claims do not inflate independent source count.

## Experiment Loop

Evidence-backed hypotheses are linked to source and bundle IDs. Candidate
experiments remain read-only and require existing authoritative real validation
before ranking or human review can proceed.

If evidence is insufficient, fixture-backed, metadata-only, or unvalidated,
promotion remains `needs_real_validation`.

## Safety

This sprint preserves:

- no live trading
- no KIS/Broker orders
- no automatic Champion promotion
- no approval bypass
- no strategy configuration mutation
- no unrestricted crawling or paywall/login bypass
- no arbitrary code execution from internet content
- no fabricated evidence or metrics

## Release Checks

New checks:

- `gaon-production-multi-source-research-contract-release-check`
- `gaon-production-web-news-research-release-check`
- `gaon-production-youtube-research-release-check`
- `gaon-production-community-idea-research-release-check`
- `gaon-production-evidence-fusion-release-check`
- `gaon-production-source-independence-release-check`
- `gaon-production-cross-source-conflict-release-check`
- `gaon-production-multi-source-experiment-loop-release-check`
- `gaon-production-research-prompt-injection-safety-release-check`
- `gaon-production-validation-sample-diagnostic-release-check`

## Schema

No database migration. Runtime schema remains v36.
