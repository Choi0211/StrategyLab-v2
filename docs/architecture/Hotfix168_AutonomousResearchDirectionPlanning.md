# Hotfix #168: Autonomous Research Direction Planning

Status: Implemented (backend only).

## Root Cause

Production investigation (pre-#168) confirmed that once a mission's bounded
9-family declarative strategy grammar (`STRATEGY_FAMILY_TEMPLATES` +
`STRATEGY_SPACE_EXPANSION_TEMPLATES`) was genuinely exhausted with no
`attempt_bounded_stagnation_recovery`-eligible candidate,
`AutonomousResearchRuntimeWorker.tick()` reported `blocked_no_recovery`
forever, every 15 minutes, with no durable record of *why* and no evidence
surfaced for what would actually unblock the mission. This was honest
(never fabricated progress) but opaque and permanently terminal:

> **Before:** bounded strategy grammar exhaustion => terminal BLOCKED,
> repeating an unexplained no-op tick indefinitely.

## Change

> **After:** bounded strategy grammar exhaustion => evidence-backed
> autonomous research-direction planning (`gaon.research.research_direction`),
> reachable only from that exact dead end, still resolving to an honest
> `AWAITING_EVIDENCE` state when (as is the structurally-guaranteed case
> today) no live candidate or untried family remains to act on.

A new stage - EXHAUSTED -> FAILURE ANALYSIS -> RESEARCH PRIORITY ->
RESEARCH DIRECTION -> (evidence requirements surfaced) -> honest
WAITING/terminal state - runs exactly once per distinct mission state:

1. **Failure analysis** (`analyze_mission_failure`) classifies every
   terminal candidate's `rejected_reason`/`validation_stage_status` into
   one of ten structured `FailureClass` values (insufficient sample,
   economic-viability failure, cost/slippage fragility, robustness
   failure, regime sensitivity, evidence insufficiency, data/provider
   limitation, repeated validation stagnation, hypothesis-family
   exhaustion, unknown/unsupported) - reusing only already-persisted
   state, never re-running research or guessing.
2. **Research priority** reuses `gaon.research.research_priority.
   propose_research_priority` (added, previously unwired, in #166) for a
   read-only KR-vs-Binance evidence comparison, plus the durable
   Sustainability & Growth objective's `SUSTAINABILITY_DIMENSIONS` as
   read-only priority *context* (see Safety below).
3. **Research direction** (`plan_research_direction`) deterministically
   picks a `NextResearchAction` and persists a `ResearchDirection` record.

## Architecture

- New module: `src/gaon/research/research_direction.py` - pure
  classification/planning functions plus `ResearchDirectionRepository`
  (SQLite CRUD).
- New tables (migration v37->v38): `research_failure_analyses`,
  `research_directions`. Both are written only by this module.
- Wiring: `AutonomousResearchRuntimeWorker.tick()`'s BLOCKED branch calls
  `_plan_research_direction()` only when `attempt_bounded_stagnation_
  recovery` returns not-recovered AND `blocked_reason.startswith(
  "strategy_hypothesis_space_exhausted")` - every other blocked reason
  (`provider_unavailable`, `selected_symbol_universe_exhausted`, tool
  failures, ...) is untouched and still reports `blocked_no_recovery`.

## Idempotency / Bounds

Both records are stored under a deterministic id derived from
`mission_history_fingerprint` (mission's blocked reason + every
candidate's id/status/rejected_reason, sorted) and written with
`INSERT OR IGNORE`. Re-observing the same mission state on a later
15-minute tick is a cheap, bounded read (one `SELECT`), never a duplicate
row or unbounded work - this is what stops the "identical analysis record
every 15 minutes forever" failure mode the investigation flagged.
`attempt_bounded_stagnation_recovery` itself is untouched: no cooldown or
persisted attempt-counter was added to it, and its own scan bound
(`max_candidates`) is unchanged.

## Safety

- A `ResearchDirection` never mutates strategy config, creates/promotes a
  candidate, creates an approval, or executes an order - creation writes
  only to the two tables this module owns.
- `PROHIBITED_ACTIONS` on every record includes the Sustainability
  objective's `FORBIDDEN_JUSTIFICATIONS` verbatim (risk/leverage increase,
  validation relaxation, fabricated evidence, approval bypass, champion
  auto-promotion, live order execution, unauthorized fund use) plus the
  structural production actions (strategy config mutation, candidate
  promotion, approval creation, order execution, champion promotion).
- The planner never calls `LLMConversationBrain.respond()` - it is a pure
  deterministic read/plan/persist function over already-persisted state,
  so it can never produce a conversation turn and therefore can never
  pollute human conversation history or Cognitive Core feedback (the
  #164-#166 system-turn isolation is preserved by construction, not by an
  added gate).
- `MissionStatus.AWAITING_HUMAN_APPROVAL` remains a hard stop for the
  worker exactly as before this hotfix - a mission with direction history
  is still never advanced past it.

**Research autonomy is never trading/capital authority.** This principle,
already established by #165/#166, is unchanged by this hotfix: every
`ResearchDirection` this module can produce is explicitly bounded to
`NextResearchAction` values the module itself never executes - it only
classifies, prioritizes, and records for human/developer review.

## Known Limitations

- In the mission-fully-exhausted case this module is wired for today
  (all candidates terminal, no untried family), `plan_research_direction`
  always resolves to `WAIT_FOR_REQUIRED_DATA`/`AWAITING_EVIDENCE` - there
  is no reachable production capability to act further without a
  human/developer-reviewed change (e.g. extending the bounded grammar).
  This is an intentional, honest limitation, not a placeholder bug: the
  `has_untried_family`/`has_recoverable_candidate` branches exist in
  `plan_research_direction` for completeness/testability, but production
  wiring never reaches them (those cases are already handled upstream by
  `next_untried_family`/`attempt_bounded_stagnation_recovery`).
- The Sustainability objective and `research_priority.py` remain read-only
  *inputs* to the rationale/priority payload; no code path lets either one
  change the bounded action set, the recovery eligibility rules, or the
  strategy grammar itself.
- `scheduled_automation_jobs`/`scheduled_automation_runs` retention
  (unbounded row growth over time) was identified in the pre-#168
  investigation as a separate, low-coupling concern and is intentionally
  left for a follow-up rather than bundled into this hotfix.
