# Hotfix 163.2 - Autonomous Conversation Context Integrity

Status: COMPLETE

## Context

Hotfix 163.1 connected Telegram follow-ups to the autonomous research cycle.
Production acceptance testing then found that a presentation-only follow-up after
a Learning Memory summary could fall back to the normal backtest presentation
renderer.

## Problem

The conversation context stored autonomous research payloads in the same
structured-result slot used by normal `krx_real_research` and comparison
results. Presentation follow-ups such as `쉽게 설명해줘` could therefore treat an
autonomous or learning-memory payload as if it were a BacktestResult, producing
unsupported defaults such as unknown periods, zero trades, or unavailable
performance metrics.

## Fix

Hotfix 163.2 separates semantic context kinds for:

- standard single-symbol research
- comparison research
- autonomous research cycle
- autonomous continuation
- autonomous critique
- autonomous Learning Memory summary

Presentation-only follow-ups now route by `last_result_kind`. Autonomous and
Learning Memory contexts use deterministic autonomous renderers instead of the
normal BacktestResult renderer.

## Invariants

- Presentation follow-ups do not rerun research or autonomous tools.
- Learning Memory summaries only report evidence-backed stored records and
  duplicate candidates.
- Missing fields are not fabricated into `unknown` periods, `trade_count=0`, or
  calculated performance metrics.
- Telegram chat isolation remains enforced.
- No live trading, broker/KIS order, Champion auto-promotion, approval bypass,
  or strategy configuration mutation is introduced.

## Release Check

```bash
python -m gaon.runtime.cli gaon-autonomous-conversation-context-release-check --db :memory:
```

The release check simulates:

1. Samsung research
2. autonomous validation
3. autonomous critique
4. autonomous continuation
5. Learning Memory query
6. presentation-only simplification
7. cross-chat presentation isolation

Expected result:

```text
gaon-autonomous-conversation-context-release-check: PASS ... fabricated_defaults=blocked safety=pass
```
