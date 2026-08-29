# Hotfix #169A: Canonical Mutation Surface + Durable Hypothesis Proposal

Status: Implemented (backend only). **#169A is generator FOUNDATION, not
autonomous research execution.** Current flow ends at:

```
ResearchDirection -> BoundedHypothesisProposal -> READY_FOR_EVIDENCE
```

Not yet present (deliberately out of scope - see #169 Phase 2's phased
plan): external evidence acquisition, `StrategyCandidateRecord` creation,
backtest/validation execution, autonomous runtime/scheduler wiring, any
production strategy change.

## Purpose

The #169 architecture investigation found that once a mission's bounded
9-family declarative grammar is exhausted, no existing capability in this
repository can safely propose a new strategy hypothesis from evidence - not
because the *safe surface* is missing, but because nothing connects a
`ResearchDirection`'s diagnosis to a durable, novel, budget-bounded proposal
object. #169A builds exactly that connecting piece, and nothing more.

## Core Safety Principle - Free Text Is Structurally Impossible Here

```
FORBIDDEN:  LLM free text -> UserStrategyParser -> candidate
```

`gaon.research.hypothesis_proposal` never imports or calls
`UserStrategyParser` - proven by a static source-scan assertion in its own
release check (`production_bounded_hypothesis_proposal_release_check`),
mirroring the `inspect.getsource()` forbidden-reference pattern already used
by #165/#168's release checks. Every `CanonicalStrategySpec` this module
touches is either:

- an existing candidate's already-persisted `spec_rules`, reconstructed via
  the existing, reused `gaon.research.multi_symbol._strategy_from_candidate_spec`
  (never re-parsed from text), or
- the same spec with exactly one field's value deterministically replaced.

No parallel strategy model was introduced - `CanonicalStrategySpec`,
`ProvenancedValue`, `FieldProvenance`, and `strategy_family_fingerprint` are
all reused from `gaon.research.krx_real_pipeline` exactly as-is.

## Canonical Mutation Surface

`CANONICAL_MUTATION_POLICY` is the CLOSED, six-entry allowlist - exactly the
fields `RuleBasedBacktestEngine` interprets (confirmed exhaustively by the
#169 investigation; no other `entry`/`exit`/`filters` key is ever assigned
anywhere in this repository):

| field | dict | mutation method | domain (derived from `ALL_STRATEGY_FAMILY_TEMPLATES`, never invented) | autonomy class |
|---|---|---|---|---|
| `breakout_lookback` | entry | historical neighbor grid | `{10, 20, 30, 40}` | `AUTONOMOUS_ALLOWED` |
| `channel_exit_lookback` | exit | historical neighbor grid | `{7, 10, 15, 20}` | `AUTONOMOUS_ALLOWED` |
| `protective_stop_pct` | exit | historical neighbor grid | `{-8.0, -6.0, -5.0, -4.0}` | `REVIEW_REQUIRED` |
| `close_gt_ma20` | entry | boolean toggle | `{False, True}` | `AUTONOMOUS_ALLOWED` |
| `ma20_gt_ma60` | entry | boolean toggle | `{False, True}` | `AUTONOMOUS_ALLOWED` |
| `volume_gte_ma20` | filters | boolean toggle | `{False, True}` | `AUTONOMOUS_ALLOWED` |

All six are `allowed=True` (able in principle to be a mutation target) -
**none touch risk sizing, leverage, or capital**, because
`CanonicalStrategySpec` has no such field at all (a structural absence
confirmed by the investigation, not a policy choice). But `allowed` is not
the same claim as "safe to mutate autonomously" - see **Autonomy
Classification** below for the second, independent gate this hardening
pass added. `PROHIBITED_DIMENSION_NAMES` (leverage, position_sizing,
capital_allocation, daily_loss_limit, protective_stop_removed,
validation_threshold, approval_state, promotion_state, live_execution,
broker_config, order_config, quantity, cost_model, slippage) documents a
different boundary explicitly and is tested against directly - none of
those names can ever become a real policy entry at all.

**Value domains are derived, not hardcoded**: `_historical_values()` scans
`gaon.knowledge.strategy_candidate.ALL_STRATEGY_FAMILY_TEMPLATES` at import
time. If a future hotfix adds a template, this module's domains widen
automatically and consistently, with zero duplicated literals.

## Autonomy Classification (added by the post-implementation policy audit)

`MutationPolicyEntry.autonomy_class` is a second, independent,
machine-enforced gate `generate_bounded_proposals` checks for every
candidate mutation - **regardless of what `FAILURE_CLASS_MUTATION_SUPPORT`
names**:

- `AUTONOMOUS_ALLOWED`: may be produced whenever a failure-class policy
  names it (five of the six fields).
- `REVIEW_REQUIRED`: **never produced by this generator, ever** -
  `protective_stop_pct` is the one field so classified. It directly sets
  `stop_price = entry_price * (1 - abs(stop_pct)/100)`
  (`RuleBasedBacktestEngine.run`) - a genuine per-trade maximum-loss
  (risk-magnitude) parameter, unlike the other five which are pure entry/
  exit threshold logic. `HISTORICAL_NEIGHBOR_GRID`'s generic
  ascend-to-next-value rule happens to move toward a tighter stop only
  because today's fixed domain `{-8,-6,-5,-4}` makes ascending numerically
  equal to risk-decreasing - a coincidence of the current domain, not a
  property the algorithm understands or verifies. It is currently
  unreferenced by any `FAILURE_CLASS_MUTATION_SUPPORT` entry, so production
  behavior is unaffected today - but the generator itself refuses to ever
  produce a mutation for it even if a future policy update mistakenly names
  it (tested directly with an adversarial policy override).
- `FORBIDDEN`: reserved, unused today.

This is enforced **in the generator itself**, not only by the policy table
being correct - process review of `FAILURE_CLASS_MUTATION_SUPPORT` is
never trusted alone.

## Supported Failure Mappings

`FAILURE_CLASS_MUTATION_SUPPORT` is a small, versioned, human-authored
table - deliberately conservative for #169A, and hardened by a
post-implementation policy audit that traced `RuleBasedBacktestEngine`'s
actual entry/exit/cost-stress code line by line:

- **`cost_slippage_fragility`** (the real, currently-observed production
  dominant failure class) -> `("breakout_lookback",)` only.
  Rationale (human-authored, not derived at runtime, and now verified
  against the actual backtest engine code): `prior_high = max(...)` over an
  expanding window is provably monotonic non-decreasing as
  `breakout_lookback` grows, so the entry condition never becomes easier -
  fewer, more selective breakout signals are a structural (not merely
  plausible) consequence. This repository's cost model
  (`default_execution_assumptions`) charges `cost_rate` on every round-trip
  trade fill, never as a function of holding duration, so reduced entry
  frequency has a direct, code-grounded mechanism to reduce
  `transaction_cost_stress` degradation
  (`autonomous_quant_partner.py:_execute_cost_stress`). **This is a
  code-grounded, directional hypothesis worth investigating - it does NOT
  assert that increasing `breakout_lookback` resolves `cost_slippage_
  fragility` for any specific candidate, only that gathering validation
  evidence in this direction is legitimate.** Failure class alone never
  proves causal resolution; that is exactly why the terminal state for
  #169A is `READY_FOR_EVIDENCE`, not `READY_FOR_APPROVAL`.

  `channel_exit_lookback` was removed from this mapping by the audit:
  `exit_n` only changes which exit path fires (channel-low vs stop vs
  end-of-dataset) - it never affects entry frequency, and total trade/
  round-trip count is governed entirely by entry conditions. Since the cost
  model has no holding-duration-based cost component, "increases holding
  period, therefore reduces turnover/cost" does not hold for this field's
  actual code semantics. `channel_exit_lookback` remains a legitimate
  canonical research field (see the allowlist table above) - it is simply
  not wired to any failure class today, for lack of a code-grounded
  mechanism connecting it to `cost_slippage_fragility` specifically.

## Unsupported Failure Mappings

`economic_viability_failure` and `robustness_failure` (and every other
`FailureClass`) are **deliberately NOT mapped** - the investigation found no
`CanonicalStrategySpec` field that plausibly and specifically addresses
either. `generate_bounded_proposals` returns a single, honest
`ProposalStatus.UNSUPPORTED` record for these (never silence, matching
#168's philosophy of recording rather than no-op), with a rationale
explaining exactly why - never a fabricated mapping.

## Deterministic Value Generation

Two mechanisms, both grounded entirely in already-persisted repository data:

- **`HISTORICAL_NEIGHBOR_GRID`**: the next value strictly greater than the
  parent's current value within `_historical_values()`'s domain. Returns
  `None` (an honest bounds-exhaustion signal) when the parent is already at
  the historical maximum - **never extrapolates past 40 to invent 45 or 50**.
- **`BOOLEAN_TOGGLE`**: flips the current boolean.

No random number, no LLM-generated value, no external-text-derived number,
and no value outside the field's `allowed_values` tuple can ever appear in
a `ProposalMutation.proposed_value` - enforced by construction (the
generator only ever reads from `policy.allowed_values`) and verified by
dedicated tests.

## Mutation Budget

`MutationBudget(max_dimensions_changed_per_proposal=1, max_proposals_per_direction=2)`
- conservative defaults, scaled to existing repository convention magnitude
rather than invented from nothing:

- `max_dimensions_changed_per_proposal=1` matches the #169 investigation's
  explicit "one-dimensional mutation as default" guidance.
- `max_proposals_per_direction=2` reuses the exact magnitude of
  `attempt_bounded_stagnation_recovery`'s `max_candidates=2` scan bound
  (`gaon.runtime.autonomous_research_runtime`) - the closest existing
  precedent for "how many things this layer may consider per bounded pass."

## Novelty / Dedup

`novelty_fingerprint` reuses `CanonicalStrategySpec.strategy_family_fingerprint`
**exactly** (the real production fingerprint every existing candidate
already uses - confirmed by the investigation to already be
parameter-value-granular) computed on the mutated spec. A proposal is
`ProposalStatus.DUPLICATE` when this fingerprint matches either an existing
candidate in mission history or a previously persisted proposal for the
same session. `proposal_id` is itself deterministic
(`hash(research_direction.fingerprint, field, proposed_value)`), so
persistence (`INSERT OR IGNORE`) makes re-generation against unchanged state
a cheap idempotent no-op, mirroring `gaon.research.research_direction`
exactly.

## Lineage

Every `BoundedHypothesisProposal` carries `mission_id`,
`source_failure_analysis_id`, `research_direction_id`, and
`parent_candidate_ids` - a complete, queryable chain:

```
ResearchMission -> FailureAnalysis -> ResearchDirection -> BoundedHypothesisProposal
```

`base_strategy_spec` is the parent candidate's own already-persisted
`spec_rules` (unmutated); the resulting mutated spec is always derivable
from `base_strategy_spec` + `mutations`, never stored redundantly. A future
#169E, when it promotes a proposal to a real `StrategyCandidateRecord`, can
reuse `StrategyCandidateRecord`'s existing (already-migrated, currently
unused) `parent_candidate_id`/`generation` fields directly - no new lineage
concept is needed there either.

## Database / Schema

**One new table** (v38 -> v39, additive only): `research_hypothesis_proposals`.
No `evidence-link` table and no `budget` table were added - `evidence_refs`
lives as a JSON column on the proposal row (matching #168's
`evidence_candidate_ids_json` pattern), and budget consumption is derivable
via `COUNT(*) ... WHERE research_direction_id = ?` against the one new
table. No existing table is touched (`CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS` only - no `ALTER`/`DROP`/`DELETE`). Confirmed
idempotent (re-running `migrate()` against an already-v39 database is a
verified no-op) and, following the exact v38 precedent, safe against a
large production database (new-table/new-index creation touches no
existing page).

## Proposal Status

`PROPOSED` (transient, pre-dedup), `REJECTED` (defensive - a field/value
failing the allowlist, structurally near-unreachable since the generator
only ever reads from the allowlist, but tested), `DUPLICATE` (fingerprint
collision), `UNSUPPORTED` (no evidence-justified mapping, or bounds
exhausted), `READY_FOR_EVIDENCE` (the terminal success state for #169A).

**`READY_FOR_EVIDENCE` is explicitly not `READY_FOR_APPROVAL`.** A proposal
is not a candidate; nothing in this module creates a
`StrategyCandidateRecord`, appends to `mission.candidates`, or reaches any
promotion/approval code path.

## Safety

- Proposal generation is a **pure, deterministic function** -
  `generate_bounded_proposals` performs no network call, no LLM call, and no
  DB write; persistence (`BoundedHypothesisProposalRepository`) is a
  separate, explicit step, so generation can be called, tested, and reasoned
  about entirely offline.
- Forbidden/risk-sensitive-dimension defense is three-layered: (1)
  `FAILURE_CLASS_MUTATION_SUPPORT` only ever names real allowlist fields
  with a code-verified mechanism, (2) a field absent from
  `CANONICAL_MUTATION_POLICY` entirely (e.g. `leverage`) is silently never
  produced regardless of what any policy mapping names, and (3) a field
  present in the allowlist but classified `REVIEW_REQUIRED`
  (`protective_stop_pct`) is *also* never produced, even if a future
  `FAILURE_CLASS_MUTATION_SUPPORT` entry mistakenly references it - all
  three are tested directly with adversarial policy overrides.
- The Sustainability & Growth objective (`gaon.cognitive.sustainability`)
  is never imported or referenced by this module at all - it remains purely
  #168's read-only research-priority context, and cannot influence dimension
  or value selection here even indirectly.
- Reused, not duplicated: `CanonicalStrategySpec`, `ProvenancedValue`,
  `FieldProvenance`, `strategy_family_fingerprint`,
  `_strategy_from_candidate_spec`, `ALL_STRATEGY_FAMILY_TEMPLATES`, and the
  `INSERT OR IGNORE` idempotent-persistence pattern from
  `gaon.research.research_direction`.

## Tests

`tests/unit/test_hypothesis_proposal.py` (30 tests) and
`tests/integration/test_bounded_hypothesis_proposal_production.py` (4 tests,
through the real `TelegramConversationAgent` stack) cover: structured
canonical input -> bounded proposal; no free text/LLM involvement; budget
enforcement; disallowed-field/out-of-bounds-value rejection; determinism
(no randomness); dedup against both existing candidates and prior
proposals; honest `UNSUPPORTED` for unmapped failure classes and for
bounds-exhausted dimensions; mission/candidate/strategy/order/Champion/
approval state unchanged before/after; Sustainability objective cannot
reach the mutation surface; schema v38->v39 idempotency; durability across a
simulated restart; full mission->failure-analysis->direction->proposal
lineage traceability; `READY_FOR_EVIDENCE` never conflated with
`READY_FOR_APPROVAL`. A dedicated `PolicyHardeningTests` class (added by the
post-implementation policy audit) additionally verifies:
`cost_slippage_fragility` still produces a `breakout_lookback` proposal;
`channel_exit_lookback` is never produced for that failure class;
`protective_stop_pct` is never produced even when a malicious/misconfigured
policy override names it (with a sibling `AUTONOMOUS_ALLOWED` field in the
same override still working normally); `protective_stop_pct` alone in a
mapping resolves honestly to `UNSUPPORTED`, never silently empty;
`protective_stop_pct`'s `autonomy_class` is exactly `REVIEW_REQUIRED` and
the other five fields are exactly `AUTONOMOUS_ALLOWED`; boolean fields are
not activated by this hardening pass; arbitrary forbidden fields
(`leverage`/`position_size`) remain blocked; budget/dedup/lineage/
durability behavior is unchanged; all safety tables remain untouched.

## Release Check

`gaon-production-bounded-hypothesis-proposal-release-check` (CLI-wired)
reproduces the exact real production failure breakdown reported for #168
(`cost_slippage_fragility=4, regime_sensitivity=2, robustness_failure=2,
economic_viability_failure=1`) end-to-end through the real
`TelegramConversationAgent`/repository stack, with real before/after
table-count observation (not by-construction constants) for every
strategy/order/Champion/approval table. Hardened by the policy audit to
additionally assert: `cost_mapping_grounded` (the cost_slippage_fragility
mapping is exactly `("breakout_lookback",)`), `unsupported_exit_mapping_
rejected` (`channel_exit_lookback` is absent from both the mapping and
every generated mutation), and `risk_sensitive_mutation_guarded`
(`protective_stop_pct` is never produced even under an adversarial
failure-class policy override naming it alongside a legitimate field).

## Known Limitations

- Only `cost_slippage_fragility` has a supported mutation mapping in
  #169A, and only `breakout_lookback` within it (post-audit) - by design,
  per the explicit instruction not to fabricate meaning for
  `economic_viability_failure`/`robustness_failure`, and per the audit's
  finding that `channel_exit_lookback` has no code-grounded turnover/cost
  mechanism. Extending coverage is a future, separately-reviewed
  policy-table change, not a code change.
- `channel_exit_lookback`/`close_gt_ma20`/`ma20_gt_ma60`/`volume_gte_ma20`
  are marked `allowed=True, autonomy_class=AUTONOMOUS_ALLOWED` in
  `CANONICAL_MUTATION_POLICY` (they are safe, research-only threshold/
  filter fields, distinct from the risk-magnitude `protective_stop_pct`)
  but are not yet referenced by any `FAILURE_CLASS_MUTATION_SUPPORT` entry.
  Boolean fields additionally need direction-aware logic (not a bare
  `BOOLEAN_TOGGLE`) before any future wiring, since toggling an
  already-True filter off would loosen selectivity - the wrong direction
  for a turnover-reduction hypothesis.
- `protective_stop_pct` is permanently `REVIEW_REQUIRED` and the generator
  refuses to ever produce a mutation for it, regardless of future policy
  changes - promoting it to `AUTONOMOUS_ALLOWED` would require a separate,
  explicit design decision (a field-aware direction concept that
  understands "which way is riskier" is not something this module has
  today), not a policy-table edit alone.
- No external evidence acquisition, candidate creation, or validation
  execution exists yet - `READY_FOR_EVIDENCE` proposals are inert records
  until a future, separately-approved phase (#169B onward) connects them to
  the next step.
