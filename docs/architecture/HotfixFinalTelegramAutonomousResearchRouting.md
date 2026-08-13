# Hotfix: Final Telegram Autonomous Research Routing

Status: COMPLETE

## Problem

Final production acceptance found that a compound Samsung autonomous research
request containing external research, learning memory, real market data,
robustness validation, candidate generation, and promotion-readiness language
could fall through to the generic stock-analysis persona instead of the
authoritative Autonomous Learning V2 route.

The stale persona also claimed that real market data and backtest execution were
not connected, which is no longer true for explicit read-only research requests.

## Root Cause

The Telegram/conversation routing stack used separate deterministic gates for
memory search, legacy retest, multi-symbol research, and Autonomous Learning V2.
Requests containing memory terms such as "research memory" could be rejected by
the V2 conversational gate before later V2-specific signals were considered.
Meanwhile, generic stock-analysis fallback text still described an older
pre-production capability model.

## Fix

- Added an explicit UTF-8 autonomous-learning intent gate for compound V2
  research requests.
- Preserved multi-symbol priority unless the request contains explicit V2
  signals such as external research, learning-memory synthesis, promotion
  review, or "research again from scratch".
- Preserved simple legacy retest/continuation routing.
- Added routing diagnostics for V2 evidence, selected route, fallback reason,
  and production capability visibility.
- Replaced stale generic stock/backtest persona text with a truthful safe-tool
  capability statement.

## Invariants

- No live trading.
- No KIS/Broker orders.
- No automatic Champion promotion.
- No approval bypass.
- No strategy mutation.
- No fixture promotion path.
- Schema remains v36.
