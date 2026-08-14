# Gaon V2 Final Research Capability Closeout

Status: COMPLETE in deterministic release validation; PENDING PRODUCTION VERIFICATION for live Telegram/provider execution.

## Context

Gaon V2 already has the production research engine, safe Telegram routing, real KRX/Yahoo market-data grounding, multi-source evidence contracts, robustness validation, learning memory, tournament ranking, and two-stage human approval. This closeout does not add a duplicate research engine or conversation engine. It tightens the final production capability contract around the existing Autonomous Quant Partner path.

## Goals

- Keep normal Telegram responses natural and Korean by default.
- Hide implementation/debug states unless the user asks for detail/raw output.
- Verify that external research is diversified across independent source categories.
- Verify provider fallback continues when one source category is unavailable.
- Verify counter-evidence, adaptive iteration, validation feedback, sample adaptation, memory reuse, robustness reuse, provenance, and approval boundaries as one aggregate contract.

## Natural Conversation Policy

Default answers may say what was studied, what was validated, what is weak, and why approval is or is not ready. They must not expose raw internal states such as `multi_symbol_partial`, `insufficient_primary_sample`, `cost_fragile`, `research_budget_exhausted`, source IDs, fingerprints, or payload/tool wording.

Detail/raw requests still expose diagnostic fields for operations. This keeps Telegram useful for users while preserving machine-checkable debugging when explicitly requested.

## Provider Matrix

The final capability check reuses the existing `SourceCategory` contract:

- Tier A: academic, official_market, corporate, regulatory.
- Tier B: professional_research.
- Tier C: news, web.
- Tier D: youtube, community, social.

Low-credibility Tier D evidence can inform ideas, but cannot alone support promotion. Metadata-only and fixture-backed evidence cannot become promotion evidence.

## Adaptive Research Loop

The bounded loop keeps `max_iterations` and chooses next actions from structured gaps:

- diversify sources
- search counter evidence
- expand validation
- run tournament
- stop at human approval or fail-closed blockers

Sample insufficiency does not lower the minimum trade count. It records horizon-extension attempts and keeps approval blocked until sufficient evidence exists.

## Validation Feedback

Robustness sections are reused from the existing validation path:

- multi-symbol
- OOS
- walk-forward
- regime validation
- parameter sensitivity
- transaction-cost stress
- Monte Carlo when enough actual trade-return series exists

Validation failures feed the unified promotion-readiness gate and the next research action. Metrics remain evidence-backed; fabricated metrics remain blocked.

## Research Memory

Learning memory preserves failed hypotheses, contradictory evidence, duplicate candidate fingerprints, and freshness policy. The closeout verifies that duplicate candidate fingerprints are not regenerated as new research.

## Approval Boundary

The two-stage approval contract remains unchanged:

1. Stage 1 freezes the candidate snapshot for review.
2. Stage 2 is required before Champion replacement.

No strategy mutation, Champion auto-promotion, live trading, KIS order, or broker order is performed by this closeout.

## Release Checks

Focused checks:

```bash
python -m gaon.runtime.cli gaon-production-natural-conversation-polish-release-check
python -m gaon.runtime.cli gaon-production-no-internal-status-leakage-release-check
python -m gaon.runtime.cli gaon-production-real-external-provider-diversification-release-check
python -m gaon.runtime.cli gaon-production-independent-source-acquisition-release-check
python -m gaon.runtime.cli gaon-production-provider-fallback-continuation-release-check
python -m gaon.runtime.cli gaon-production-counter-evidence-query-execution-release-check
python -m gaon.runtime.cli gaon-production-adaptive-research-iteration-release-check
python -m gaon.runtime.cli gaon-production-validation-feedback-action-release-check
python -m gaon.runtime.cli gaon-production-sample-insufficiency-adaptation-release-check
python -m gaon.runtime.cli gaon-production-horizon-extension-policy-release-check
python -m gaon.runtime.cli gaon-production-research-memory-reuse-release-check
python -m gaon.runtime.cli gaon-production-no-duplicate-candidate-fingerprint-release-check
python -m gaon.runtime.cli gaon-production-robustness-reuse-release-check
python -m gaon.runtime.cli gaon-production-evidence-provenance-integrity-release-check
python -m gaon.runtime.cli gaon-production-low-credibility-promotion-block-release-check
python -m gaon.runtime.cli gaon-production-no-fabricated-metrics-final-release-check
python -m gaon.runtime.cli gaon-production-two-stage-approval-preserved-release-check
python -m gaon.runtime.cli gaon-production-no-strategy-mutation-before-approval-release-check
python -m gaon.runtime.cli gaon-production-no-live-order-execution-release-check
python -m gaon.runtime.cli gaon-production-telegram-authoritative-path-reuse-release-check
python -m gaon.runtime.cli gaon-production-no-duplicate-research-engine-release-check
```

Aggregate check:

```bash
python -m gaon.runtime.cli gaon-production-final-research-capability-closeout-release-check
```

Expected aggregate fields:

```text
NATURAL_CONVERSATION=pass
EXTERNAL_RESEARCH=pass
SOURCE_DIVERSIFICATION=pass
INDEPENDENT_EVIDENCE=pass
COUNTER_EVIDENCE=pass
ADAPTIVE_LOOP=pass
VALIDATION_FEEDBACK=pass
SAMPLE_ADAPTATION=pass
MEMORY_CONTINUITY=pass
ROBUSTNESS_REUSED=pass
PROVENANCE=pass
TWO_STAGE_APPROVAL=pass
DUPLICATE_ENGINE=false
FABRICATED_METRICS=false
ORDER_EXECUTED=false
safety=pass
```

## Remaining Production Limitations

- Live Telegram acceptance with configured real external providers must still be verified on the VPS.
- Provider categories that are not configured must remain honestly reported as unavailable.
- The release validation proves wiring and fail-closed contracts; it does not claim that every external provider is reachable in a given production environment.

## Rollback

Rollback is a normal Git revert of this closeout commit. No schema migration is introduced, so database rollback is not required.
