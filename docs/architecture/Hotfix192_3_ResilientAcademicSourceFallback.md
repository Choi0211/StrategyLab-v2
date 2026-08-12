# Hotfix 192.3 - Resilient Academic Source Fallback

## Status

COMPLETE

## Context

Production Autonomous Learning V2 discovery now returns relevant academic
trading research, but the first selected DOI may fail resolution with publisher
access controls such as HTTP 403. The production loop previously selected one
content source, so a single unavailable publisher prevented the rest of the
relevant candidate set from being attempted.

## Root Cause

`ExternalResearchExecutionPolicy.max_sources` controlled too many independent
budgets at once: discovery result count, relevant candidate count, resolution
attempts, acquisition attempts, and acquired source count. Telegram production
configured this value as `1`, so the executor sorted relevant results, truncated
to one source, and stopped after the first source failed.

## Design

Hotfix 192.3 separates source discovery and source success budgets:

- provider calls: 1
- discovery results: 5
- relevant candidates: 5
- DOI/content resolution attempts: 3
- content acquisition attempts: 3
- acquired sources: 2
- grounded evidence sources: 2

Relevant candidates are attempted in deterministic relevance order. Resolution
or acquisition failure is recorded and the next independent relevant source is
attempted while budget remains. The loop stops after evidence sufficiency,
acquired source budget, attempt budget, total byte budget, or candidate
exhaustion.

## Safety

HTTP 403 remains a hard failure for that source. The code does not spoof access,
scrape blocked publishers, bypass paywalls, broaden arbitrary URL access, or
weaken HTTPS/content-type/host validation. Failed sources remain observability
only and never become grounded evidence.

Fixture blocking remains fail-closed. Real-data production with missing external
evidence is classified as `needs_real_validation` rather than `blocked_fixture`
unless fixture-backed evidence is actually present.

## Observability

The external research payload now exposes:

- `discovered_result_count`
- `relevant_result_count`
- `resolution_attempt_count`
- `acquisition_attempt_count`
- `acquired_source_count`
- `grounded_source_count`
- `exhausted_source_candidates`
- `source_attempts`

Each source attempt includes title, DOI, relevance score, resolution status,
acquisition status, failure kind, and evidence count.

## Release Checks

- `gaon-production-academic-source-fallback-release-check`
- `gaon-production-academic-source-budget-release-check`
- `gaon-production-autonomous-learning-state-semantics-release-check`

These checks prove first-source DOI failure fallback, bounded source attempts,
duplicate DOI non-retry, and correct promotion/hypothesis state semantics.
