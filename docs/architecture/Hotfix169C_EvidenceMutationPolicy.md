# Hotfix #169C: Normalized Evidence -> Allowed Mutation Concept/Policy

Status: Implemented (backend only). Current flow:

```
ResearchDirection + DirectionEvidenceAcquisition (#169B)
    -> normalized structured evidence interpretation
    -> human-authored policy
    -> bounded MutationConcept
    -> AllowedMutationPolicy (allowed / review-required / forbidden dimensions)
    -> STOP
```

Not present (deliberately out of scope for this hotfix): mutating a real
`CanonicalStrategySpec`, creating a `BoundedHypothesisProposal`, creating a
`StrategyCandidateRecord`, running a backtest/validation, any
scheduler/autonomous-runtime wiring, Champion promotion, approval bypass,
production apply, or trading/orders.

## 1. Purpose

#169B gave the system real, structured, direction-level evidence
(`DirectionEvidenceAcquisition`) - but nothing yet decided what that
evidence is actually *allowed to be used for*. #169C answers exactly one
question, deterministically: given a failure class and its structured
evidence state, which bounded "mutation concept" may be considered for
RESEARCH, and on which closed-allowlist `CanonicalStrategySpec` dimensions
- never which numeric value, never whether the mutation is good, never
whether it may reach production.

## 2. Architecture

```
FailureAnalysis (#168)
    -> ResearchDirection (#168)
    -> DirectionEvidenceAcquisition (#169B, or None if not yet acquired)
    -> evaluate_evidence_mutation_policy()
    -> EvidenceMutationPolicyDecision
    -> EvidenceMutationPolicyRepository (schema v41)
```

`evaluate_evidence_mutation_policy` is pure and deterministic: no network
call, no DB write, no randomness, no LLM call, no wall-clock dependency
beyond the caller-supplied `now`. Persistence is a separate, explicit step,
mirroring #169A/#169B's own generate-then-persist separation.

## 3. Evidence-Is-Not-Instruction Boundary

Every external string #169B's pipeline ever touched (title, abstract, DOI,
URL, publisher, blocker text) was already confined to #169B's own
`external_content_policy == "evidence-not-instruction"` invariant. #169C
adds a second, independent boundary on top: it never even RECEIVES that
text. Its only inputs are #169B's already-normalized, structured fields -
`RequirementResult.state` (an enum), `.evidence_source_count` (an int),
`.kind` (an enum), and `FailureAnalysis.dominant_failure_class` (an enum).
`RequirementResult.blockers` (free-form diagnostic strings) and
`ResearchDirection.rationale` (free-form prose) are never read by this
module at all - proven directly by `MaliciousInputTests` (rationale/blocker
injection tests) in `test_evidence_mutation_policy.py`.

## 4. Structured Inputs Only

```python
def evaluate_evidence_mutation_policy(
    direction: ResearchDirection,
    analysis: FailureAnalysis,
    evidence: DirectionEvidenceAcquisition | None,
    *,
    now: str,
) -> EvidenceMutationPolicyDecision
```

The function reads: `analysis.dominant_failure_class`,
`evidence.requirement_results[*].kind/.state/.evidence_source_count`,
`evidence.session_ref/.research_direction_id/.failure_class` (for a
lineage-consistency check), and this module's own hardcoded policy tables.
Nothing else.

## 5. MutationConcept Model

```python
class MutationConcept(str, Enum):
    REDUCE_ENTRY_FREQUENCY = "reduce_entry_frequency"
```

Deliberately a single member - conservative scope, matching #169A's own
conservative `FAILURE_CLASS_MUTATION_SUPPORT` (one mapped failure class). A
second concept is added only when a future failure class has an equally
code-grounded, human-reviewed rationale, never speculatively.

```python
FAILURE_CLASS_MUTATION_CONCEPT: Mapping[FailureClass, MutationConcept] = {
    FailureClass.COST_SLIPPAGE_FRAGILITY: MutationConcept.REDUCE_ENTRY_FREQUENCY,
}
```

## 6. Research-Only Permission Semantics

`PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH` means exactly one thing:
"a bounded, evidence-grounded hypothesis MAY be generated and validated for
this concept/dimension" - never "this mutation is correct," never "this
strategy is production-ready." The operational component
(`cost_model_matches_live_execution`) stays visibly
`REQUIRES_OPERATIONAL_EVIDENCE` inside `evidence_state` even when
`policy_status` is eligible - eligibility for research is never confused
with full validation.

## 7. Evidence Sufficiency Rules

The academic component (`transaction_cost_slippage_sensitivity`) must be in
`{ACQUIRED, PARTIAL}` **and** have `evidence_source_count > 0`. Any of
`PENDING`, `UNMET_REQUIREMENT`, `PROVIDER_NOT_CONFIGURED`,
`FAILED_RETRYABLE`, `FAILED_TERMINAL` - or a missing academic component
entirely, or `evidence=None` - resolves to
`PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE`. **Failure class alone is
never sufficient** - the #169A final policy audit's central finding,
preserved here structurally: a supported failure class with no qualifying
evidence is always blocked, never eligible (`test_J_failure_class_alone_
without_evidence_is_blocked`).

## 8. Partial Evidence Policy

`PARTIAL` (source count > 0) is treated identically to `ACQUIRED` for
eligibility purposes - a deliberate, documented choice, not an oversight.
#169B's own reused, unmodified `KnowledgeConflictDetector` requires two
independent supporting sources before a topic clears "insufficient
independence"; requiring `ACQUIRED` here would make eligibility
structurally unreachable given the current provider/screening
architecture (a permanent deadlock, not a temporary gap). `PARTIAL` +
real, non-zero evidence is real, genuinely-acquired evidence - just not yet
independently corroborated - and is explicitly named as
research-only permission, never a production claim (see Section 6).

## 9. Canonical Dimension Allowlist

Every dimension #169C can ever name comes from the same CLOSED, six-entry
`gaon.research.hypothesis_proposal.CANONICAL_MUTATION_POLICY` allowlist
#169A already established - reused unchanged, never duplicated. The
classification choke point (`_classify_canonical_dimension`) is
deliberately ordered as defense-in-depth:

1. `field in PROHIBITED_DIMENSION_NAMES` -> `forbidden` (leverage,
   position_size, capital_allocation, ... - reused verbatim from #169A).
2. `field not in CANONICAL_MUTATION_POLICY` -> `forbidden` (an
   arbitrary/unknown name - there is no path by which this module can ever
   name a dimension outside the six-entry allowlist).
3. `CANONICAL_MUTATION_POLICY[field].autonomy_class is REVIEW_REQUIRED` ->
   `review_required` - checked **before** the failure-class-specific
   allowed set, so a maliciously/mistakenly crafted allowed-set can never
   upgrade `protective_stop_pct` to allowed (see Section 12).
4. `CANONICAL_MUTATION_POLICY[field].autonomy_class is FORBIDDEN` ->
   `forbidden`.
5. Otherwise (canonically `AUTONOMOUS_ALLOWED`): the field must ALSO be
   explicitly named by `FAILURE_CLASS_MUTATION_SUPPORT` for this specific
   failure class, or it is still `forbidden` for this concept mapping (see
   `channel_exit_lookback`, Section 11).

`MUTATION_CONCEPT_CONSIDERED_DIMENSIONS` names, purely for output
transparency, which fields #169A's own investigation actually considered
for `REDUCE_ENTRY_FREQUENCY` (`breakout_lookback`, `channel_exit_lookback`,
`protective_stop_pct`) - this table can only narrow/annotate what
`CANONICAL_MUTATION_POLICY`/`FAILURE_CLASS_MUTATION_SUPPORT` already say;
it never grants a dimension autonomy it doesn't already have.

## 10. breakout_lookback INCREASE_ONLY Reasoning

Reused verbatim from the #169A final policy audit
(`docs/architecture/Hotfix169A_CanonicalBoundedHypothesisProposal.md`):
`RuleBasedBacktestEngine`'s `prior_high = max(...)` over an expanding
window is provably monotonic non-decreasing as `breakout_lookback` grows,
so increasing it never makes the breakout entry condition easier - same or
fewer entries, exactly the direction `REDUCE_ENTRY_FREQUENCY` needs.
Decreasing it has the opposite, unwanted effect. #169C does not re-derive
this reasoning; it reuses #169A's already-reviewed conclusion via a small,
new, explicit direction table:

```python
CANONICAL_DIMENSION_DIRECTION: Mapping[str, MutationDirection] = {
    "breakout_lookback": MutationDirection.INCREASE_ONLY,
}
```

#169C never selects the actual bounded value within that direction - only
the direction itself. #169D will pick the value from the historical grid
(`_next_historical_value`, already implemented in #169A).

## 11. channel_exit_lookback Rejection

`channel_exit_lookback` is canonically `AUTONOMOUS_ALLOWED` in
`CANONICAL_MUTATION_POLICY` (it is a real, structurally-safe field), but it
is **not** in `FAILURE_CLASS_MUTATION_SUPPORT[COST_SLIPPAGE_FRAGILITY]` -
the #169A audit found no code-grounded mechanism connecting it to cost:
`exit_n` only changes which exit path fires, never entry frequency/trade
count, and this repository's cost model charges per round-trip trade, not
per holding period. #169C's classification order (Section 9, step 5)
therefore lands it in `forbidden_dimensions` for this concept mapping - a
field can be canonically safe in general and still rejected for a specific
evidence-to-concept mapping.

## 12. protective_stop_pct REVIEW_REQUIRED

`protective_stop_pct` directly sets per-trade maximum loss
(`stop_price = entry_price * (1 - abs(stop_pct)/100)`,
`RuleBasedBacktestEngine.run`) - a genuine risk-magnitude parameter, marked
`MutationAutonomyClass.REVIEW_REQUIRED` in `CANONICAL_MUTATION_POLICY`.
Because #169C's classification checks `autonomy_class` **before** any
failure-class-specific allowed set, no evidence state and no crafted
"allowed dimensions" input can ever upgrade it to `allowed` -
`test_O2_malicious_allowed_set_cannot_upgrade_protective_stop_pct` proves
this directly by calling the classifier with a deliberately malicious
allowed-set containing `protective_stop_pct`.

## 13. Risk/Leverage Forbidden

`leverage`, `position_size`, `position_sizing`, `capital_allocation`,
`initial_capital`, `daily_loss_limit`, and the rest of
`PROHIBITED_DIMENSION_NAMES` are reused verbatim from #169A - checked
first, before even the canonical-allowlist lookup. `CanonicalStrategySpec`
has no field for any of these today (confirmed structurally absent by the
original #169 investigation) - this is a defensive, tested boundary, not a
live escape hatch.

## 14. Unsupported Failure Classes

Any `FailureClass` not a key of `FAILURE_CLASS_MUTATION_CONCEPT` resolves
to `PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS`, honestly, with zero
mutation concepts and zero dimensions - never a fabricated mapping, never
inherited from a neighboring failure class.
`robustness_failure`/`regime_sensitivity`/`economic_viability_failure`/
`insufficient_sample` are explicitly tested
(`test_I2_all_documented_unsupported_classes_never_inherit_cost_mapping`).

## 15. Policy Versioning

```python
EVIDENCE_MUTATION_POLICY_VERSION = 1
```

Included directly in the decision's fingerprint (see Section 16). A future,
human-reviewed policy revision bumps this constant, producing a NEW,
auditable decision for the same direction/evidence rather than silently
reinterpreting a past one's meaning.

## 16. Persistence / Idempotency

New, additive table `research_evidence_mutation_decisions` (schema v40 ->
v41, `gaon.runtime.migrations._upgrade_v40_to_v41`). Idempotency uses a
`(session_ref, fingerprint)` unique index and `INSERT OR IGNORE` - the same
session-scoped convention `research_hypothesis_proposals` (#169A) and
`research_direction_evidence` (#169B) already established.

```
fingerprint = sha256(
    policy_version | direction.session_ref | direction.fingerprint |
    analysis.fingerprint | (evidence.fingerprint or "no-evidence")
)[:32]
```

No random IDs, no wall-clock in the fingerprint. The same
session/direction/evidence-acquisition/policy-version combination always
produces the same `decision_id`/`fingerprint`; a different evidence
acquisition (different `evidence.fingerprint`) always produces a new one.

## 17. Authority Boundary

`gaon.research.evidence_mutation_policy` never imports
`gaon.adapters.trading`, `gaon.adapters.strategy_execution`,
`gaon.adapters.strategy_deployment`, `gaon.adapters.champion_registry`,
`gaon.knowledge.promotion_gate`, or `gaon.knowledge.human_gated_promotion`
- verified by a static `inspect.getsource()` source scan in both this
module's own release check and a dedicated unit test
(`AuthorityBoundaryTests.test_U_module_never_imports_authority_modules`).
It also never calls `generate_bounded_proposals` (the #169A generator) and
never references `run_backtest`/`place_order` - #169C stops at a policy
decision; it never invokes #169D/#169E behavior itself.
`EvidenceMutationPolicyDecision` carries no strategy/candidate/numeric
payload field at all - there is nothing here that could later be
mistaken for one.

## 18. No LLM

No OpenAI/Claude/LLM client, no embeddings, no free-text model
interpretation, no keyword extraction from external paper text, and no
generated strategy recommendation anywhere in this module. Every mutation
concept, every dimension, and every direction is a hardcoded, human-authored
constant.

## 19. No Scheduler Wiring

`gaon.research.evidence_mutation_policy` is never called from
`autonomous_research_runtime.py`'s scheduler/tick - verified by a static
source scan (`test_AD_no_autonomous_scheduler_wiring`) proving the string
`autonomous_research_runtime` never appears in this module's source.
`autonomous_research_runtime.py` itself is untouched by this hotfix.

## 20. #169D / #169E / #169F Handoff

- **#169C (this hotfix)**: normalized evidence -> allowed mutation
  concept/policy (dimension + direction only, never a value).
- **#169D**: bounded, evidence-grounded hypothesis generation - given an
  `EvidenceMutationPolicyDecision`, select the actual bounded numeric/
  boolean value (reusing #169A's `_next_historical_value`/
  `_toggled`/`HISTORICAL_NEIGHBOR_GRID` machinery) and produce a real
  `BoundedHypothesisProposal`.
- **#169E**: proposal -> `StrategyCandidateRecord` -> the existing
  validation pipeline.
- **#169F**: autonomous scheduler/runtime wiring - when and how this whole
  chain actually runs during a live mission tick.

None of #169D/#169E/#169F is implemented by this hotfix.

## 21. Safe Deployment Procedure (schema v41)

Schema bumped v40 -> v41 (additive only - one new table, no existing table
touched). This deploy must follow #170's existing Safe Deployment Procedure
(`docs/architecture/ProductionSQLiteLockStability.md`) exactly:

1. `systemctl stop strategylab-gaon`
2. `systemctl stop gaon-web`
3. Backup the database and confirm `PRAGMA quick_check = ok`.
4. Migrate once, explicitly, via the migration owner's path (e.g.
   `python -m gaon.runtime.cli db-check --db /var/lib/strategylab/gaon-runtime.sqlite`).
5. Verify the reported `schema_version` is `41`.
6. `systemctl start strategylab-gaon`
7. `systemctl start gaon-web`
8. Verify health (`db-check`/`health` CLI, and `gaon-web`'s own health
   endpoint) on both services.

No deploy was performed as part of this hotfix - implementation, tests, and
documentation only.

## Known Limitations

- `PolicyStatus` is deliberately collapsed to three values (no separate
  "partial evidence, weaker eligibility" status) - see Section 8 for why.
  The raw academic state (`ACQUIRED` vs `PARTIAL`) and source count remain
  fully visible in `evidence_state` for any caller that needs the
  distinction.
- Only `FailureClass.COST_SLIPPAGE_FRAGILITY` has a mutation-concept
  mapping. Every other failure class is honestly
  `BLOCKED_UNSUPPORTED_FAILURE_CLASS` until a future hotfix adds a
  reviewed, human-authored mapping for it.
- `MutationDirection.EITHER`/`DECREASE_ONLY` exist in the enum for
  generality but are unused today - only `INCREASE_ONLY` (for
  `breakout_lookback`) has a real mapping.
