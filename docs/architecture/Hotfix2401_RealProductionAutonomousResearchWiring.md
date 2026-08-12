# Hotfix 240.1 - Real Production Autonomous Research Wiring

Status: COMPLETE

## Context

Sprint 199-240 added the Autonomous Quant Research Partner contract and release
checks, but production Telegram responses still surfaced the legacy Autonomous
Learning V2 stage statuses. When academic content acquisition was exhausted, the
conversation appeared to stop at `academic_content_exhausted` /
`needs_real_validation` instead of showing the partner's diversification,
counter-evidence, iteration, tournament, and promotion-readiness state.

## Root Cause

The partner payload was attached under
`autonomous_learning_v2.autonomous_quant_partner`, but the Telegram-facing
status and renderer continued to read legacy V2 fields first. In addition,
`autonomous_quant_partner_payload()` used release-check fixture research when no
multi-source payload was supplied, which made direct production helper calls
unsafe unless the caller had already run production multi-source research.

## Design

- Production multi-source wiring now uses production-only adapters:
  - `production:academic_external_research` for real acquired academic evidence.
  - `production:real_market_baseline` for the real KRX/Yahoo official-market
    baseline.
  - `production:<category>:not_configured` for unavailable provider categories.
- Release-check fixture adapters are no longer the default fallback for the
  partner payload. Release checks must opt in with `allow_release_fixture=True`.
- Academic exhaustion is not terminal when other production categories provide
  evidence. The real market baseline remains an official-market source with
  provenance and content hash.
- Partner status is projected separately as
  `autonomous_quant_partner_promotion_status`; the existing top-level
  Autonomous Learning V2 contract remains backward compatible.
- Telegram rendering now prioritizes partner observability for user-facing
  progress: source categories, source IDs, counter-evidence, candidates,
  validation coverage, iterations, tournament, blockers, and promotion
  readiness.

## Safety

No live trading, KIS/Broker order, Champion auto-promotion, approval bypass,
strategy mutation, fixture promotion evidence, metadata-only promotion evidence,
or fabricated metrics are introduced.

## Verification

Targeted checks passed locally. Full verification is recorded in
`docs/tests/TestResults.md`.
