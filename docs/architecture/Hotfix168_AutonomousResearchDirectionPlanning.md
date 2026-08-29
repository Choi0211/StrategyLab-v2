# Hotfix #168 Phase 1: Research Direction Planning — Failure Diagnosis, Priority Selection, and Durable Idempotent Recording

Status: Implemented (backend only). **This is explicitly Phase 1.** Production
capability level, as verified against the real `strategy_hypothesis_space_
exhausted` production path: **LEVEL 1.5-2** (failure diagnosis + priority
selection + durable idempotent recording of a BLOCKED state - not new
hypothesis generation, not new candidate creation, not experiment execution).
See "What #168 Phase 1 Does Not Solve Yet" and "Phase 2 Direction" below for
what a later, separately-designed phase would add.

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

## What #168 Phase 1 Solves

> **After:** bounded strategy grammar exhaustion => failure analysis =>
> research priority => a durable `ResearchDirection` record => an honest
> `AWAITING_EVIDENCE` state, recorded exactly once per distinct mission
> state (see Idempotency below) instead of an unexplained repeating no-op.

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

## What #168 Phase 1 Does Not Solve Yet

There is currently **no** production path from a persisted `ResearchDirection`
to any of:

```
ResearchDirection -> new bounded hypothesis space -> new candidate generation -> experiment execution
```

This path does not exist anywhere in the repository today. A verified
gap-review (post-implementation, read-only investigation) confirmed that on
the real, fully-exhausted production mission shape (all 9 declarative
strategy families already tried and terminal, no recoverable candidate),
`plan_research_direction`'s `has_untried_family`/`has_recoverable_candidate`
branches are **structurally unreachable** - both conditions are already
guaranteed `False` by the same upstream logic (`next_untried_family`,
`attempt_bounded_stagnation_recovery`) that produced the
`strategy_hypothesis_space_exhausted` blocked reason in the first place. The
only branch production traffic can reach today resolves to
`WAIT_FOR_REQUIRED_DATA` / `AWAITING_EVIDENCE`.

## Why `next_research_action=wait_for_required_data` Fires (and what it does *not* mean)

The name `wait_for_required_data` can read as "a specific data source or
provider is missing." **On the real, fully-exhausted production mission,
that is not what it means.** Verified capabilities that already exist and
run for real in production - external/academic evidence acquisition, real
KRX/Yahoo market data fetching, the `ResearchDirector` validation-sequencing
decision layer - all execute successfully when they run at all. What is
actually missing is a different thing entirely:

> **There is no evidence-grounded bounded strategy-family generator
> capability in this repository today** - nothing that can safely propose a
> 10th/11th/... strategy family from evidence once the fixed 9-family
> grammar is exhausted. `wait_for_required_data` is the planner correctly,
> conservatively reporting *that* absence - not a data/provider shortage,
> not a missing evidence-acquisition path, and not a bug.

This action/status naming is **not changed in Phase 1** - `wait_for_required_data`
and `AWAITING_EVIDENCE` remain the persisted values `gaon.research.
research_direction` writes. Any future rename is a separate, deliberate
decision, not part of this hotfix.

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
- **Every existing evidence/research capability surveyed for this hotfix is
  either candidate-bound or market/wiring-constrained, and none of them can
  generate a new strategy family in the fully-exhausted state:**
  - Real external/academic evidence acquisition
    (`gaon.knowledge.telegram_autonomous_learning._run_production_external_research`)
    is genuine production code (real HTTPS calls, allowlisted academic
    sources), but it only annotates an *already-decided* candidate's rule
    diff with supporting/refuting citations - it requires
    `candidate.get("changed_fields")` to already exist and returns nothing
    otherwise. It cannot propose a new candidate's rules.
  - Real KRX/Yahoo market-data evidence gathering
    (`gaon.research.multi_symbol.multi_symbol_research_payload`,
    `gaon.research.krx_real_pipeline.krx_real_research_payload`) always
    requires an existing `candidate_spec`/strategy rule text as input -
    there is no "pure evidence gathering, no strategy" mode.
  - `gaon.research.research_director.ResearchDirector` (bridged via
    `gaon.knowledge.research_director_bridge`) is real, production-wired
    validation-sequencing logic, but its `ResearchDirectorState` always
    describes an *already-existing* candidate's evidence/validation
    progress; it never proposes a new one, and it is functionally parallel
    to (not a substitute for) the `next_blocker_driven_research_action`
    logic the ResearchMission flow actually uses.
  - `gaon.research.evidence.EvidenceBundle` is a generic citation
    container for narrative evidence presentation; no code path builds a
    `StrategyCandidateRecord` from it.
  - `gaon.knowledge.evidence_hypothesis.EvidenceBackedHypothesisGenerator`
    is a *validator*, not a generator - its caller must already supply
    `changed_rules`/`rationale`/`mechanism`. Its one real production
    caller, `gaon.knowledge.price_action_knowledge`, is scoped exclusively
    to Binance (`priceaction.binance.*` topic namespace, hand-authored
    Nison/Brooks candlestick content) and is reachable only via a manual
    CLI release-check - not wired into any autonomous research loop, and
    not applicable to a KR/KOSPI+KOSDAQ mission even if it were.
- The Sustainability objective and `research_priority.py` remain read-only
  *inputs* to the rationale/priority payload; no code path lets either one
  change the bounded action set, the recovery eligibility rules, or the
  strategy grammar itself.
- `scheduled_automation_jobs`/`scheduled_automation_runs` retention
  (unbounded row growth over time) was identified in the pre-#168
  investigation as a separate, low-coupling concern and is intentionally
  left for a follow-up rather than bundled into this hotfix.

## Schema v38 Deployment Characteristics

- **Additive migration only.** `_upgrade_v37_to_v38` contains exclusively
  `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` /
  `CREATE UNIQUE INDEX IF NOT EXISTS` statements - no `ALTER`, `DROP`, or
  `DELETE` anywhere.
- **2 new, empty tables** (`research_failure_analyses`, `research_directions`)
  with 4 indexes total; nothing else in the schema is touched.
- **Idempotent**: re-running `migrate()` against an already-v38 database is
  a verified no-op (`IF NOT EXISTS` on every statement; no duplicate
  `schema_version` row is inserted).
- **No existing-table rewrite or scan.** Verified empirically: applying
  this migration against a database with a 200,000-row (~100MB+) simulated
  pre-existing table completed in under 1ms - creating a new empty table/
  index touches no page of any existing table, so cost is independent of
  overall database size (relevant for the 670MB+ production database).
- **Fail-closed startup on migration failure.** `RuntimeStateStore.__init__`
  calls `migrate(self._connection)` unguarded at construction time, before
  the CLI's own `try/finally` block begins; a migration failure (e.g. a
  corrupted database, or a future binary downgrade tripping the explicit
  `current_version > SCHEMA_VERSION` guard) propagates as an uncaught
  exception and the process exits non-zero rather than continuing with a
  partially-migrated or unmigrated database.

## Phase 2 Direction (Not Implemented - Requires Separate Design Review)

**Goal: Evidence-Grounded Bounded Hypothesis Generation.**

Phase 1 stops at an honest `AWAITING_EVIDENCE` record because no capability
in this repository can safely close the loop back to a new candidate. A
future Phase 2 would need to design (not merely wire up) a path such as:

```
evidence -> failure lessons -> research direction -> bounded hypothesis proposal -> canonical validation -> candidate -> existing validation pipeline
```

**This is explicitly a design question for a separate review, not a
decision made by this document.** In particular, simply continuing to add
more human-authored declarative templates (the same shape as
`STRATEGY_SPACE_EXPANSION_TEMPLATES`) must not be assumed to be the final
autonomy architecture - it is one option among several a Phase 2 design
review would need to weigh (versus, for example, a more general bounded
hypothesis-proposal representation), and any Phase 2 implementation
requires its own explicit approval before work begins.

Whatever shape Phase 2 takes, it extends **research autonomy only**, never
capital/trading authority, and must continue to uphold every constraint
already established by #165/#166/#168 Phase 1:

- no arbitrary/unbounded strategy generation
- no validation relaxation
- no fixture-as-real
- no Champion auto-promotion
- no approval bypass
- no production auto-apply
- no live order authority
