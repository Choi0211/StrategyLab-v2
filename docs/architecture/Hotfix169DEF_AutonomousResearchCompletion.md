# Hotfix #169D-F: Autonomous Research Completion

Status: Implemented (backend only). Completes the chain #168/#169A/#169B/
#169C started:

```
ResearchMission BLOCKED/exhausted
    -> FailureAnalysis -> ResearchDirection (#168)
    -> DirectionEvidenceAcquisition (#169B)
    -> EvidenceMutationPolicyDecision (#169C)
    -> bounded value selection (#169D) -> BoundedHypothesisProposal (#169A model, reused)
    -> StrategyCandidateRecord (#169E, research-only)
    -> the EXISTING mission-driven validation/robustness/promotion cycle
    -> MissionStatus.AWAITING_HUMAN_APPROVAL (the existing READY_FOR_APPROVAL gate)
    -> HARD STOP - human action required
```

`autonomous_research_runtime.py` wires this chain into the existing
scheduler (#169F) at exactly one bounded stage per tick.

## 1. Purpose

#169C decided WHICH mutation concept/dimension MAY be researched. Nothing
before this hotfix ever picked an actual value, created a candidate, or let
that candidate enter validation. #169D-F closes that gap using only
already-existing, already-audited machinery - #169A's own
`generate_bounded_proposals`, the existing `StrategyCandidateRecord`/
`ResearchMission` model, and the existing mission-driven validation cycle
(`LLMConversationBrain._try_mission_driven_research_cycle`/
`_try_candidate_robustness_cycle`) - never a new engine.

## 2. Architecture

Two new, narrow modules plus one extension of the existing scheduler:

- `gaon.research.bounded_hypothesis_generation` (#169D): gates #169A's
  `generate_bounded_proposals` behind #169C's
  `EvidenceMutationPolicyDecision.policy_status`. Contains no value-
  selection logic of its own.
- `gaon.research.proposal_candidate_bridge` (#169E): builds exactly one
  `StrategyCandidateRecord` from a `READY_FOR_EVIDENCE` proposal and hands
  it to the mission via the existing `add_candidate`/`set_active_candidate`
  functions. Contains no validation logic of its own.
- `gaon.runtime.autonomous_research_runtime._advance_evidence_mutation_
  chain` (#169F): the one new stage-progression method inside the existing
  `AutonomousResearchRuntimeWorker`, reachable only when a mission is
  BLOCKED on `strategy_hypothesis_space_exhausted` for a #169C-supported
  failure class. Every non-`cost_slippage_fragility` failure class's
  behavior is completely unchanged from #168.

Dependencies flow strictly one way: direction/evidence/policy -> proposal
-> candidate -> the existing validation stack -> the existing Web read
endpoints. Nothing here imports Web code, and nothing in Web imports this
chain's internals.

## 3. #169D: Bounded Hypothesis Value Selection

`generate_bounded_hypothesis(decision, direction, analysis, candidate_history, ...)`
is a gate, not a generator:

- `decision.policy_status is not ELIGIBLE_FOR_HYPOTHESIS_RESEARCH` ->
  delegates to `generate_bounded_proposals(..., failure_class_support={})`,
  which returns #169A's own honest `UNSUPPORTED` proposal - never a
  fabricated mutation, never a fallback to the failure class alone.
- Otherwise, delegates to `generate_bounded_proposals` restricted to the
  INTERSECTION of #169C's `allowed_dimensions` and #169A's own audited
  `FAILURE_CLASS_MUTATION_SUPPORT` for this failure class - defense-in-
  depth that can never smuggle in a dimension #169A itself would refuse.

Every actual bounded value comes from #169A's unmodified
`_next_historical_value`/`HISTORICAL_NEIGHBOR_GRID` machinery - the same
closed, already-audited historical domain (e.g. `{10, 20, 30, 40}` for
`breakout_lookback`), always moving strictly upward from the parent
candidate's current value (INCREASE_ONLY, matching #169C's
`CANONICAL_DIMENSION_DIRECTION`). `generate_bounded_hypothesis`'s own
signature has no parameter through which a caller could ever supply a
numeric value - proven directly by
`test_D_no_arbitrary_numeric_input_accepted`.

Lineage is preserved via a new, additive
`HypothesisExecutionLineageRepository` (see Section 10) linking
`proposal_id -> research_direction_id, evidence_acquisition_id,
policy_decision_id`, and later `candidate_id` - `BoundedHypothesisProposal`
(#169A's own model) is reused completely unmodified.

## 4. #169E: Proposal -> Candidate -> Existing Validation

`create_candidate_from_proposal`/`advance_mission_with_candidate` build
exactly ONE new `StrategyCandidateRecord`:

- reconstructs the parent's spec via `_strategy_from_candidate_spec`
  (#169A's own reconstruction path, reused identically);
- applies EXACTLY the proposal's one mutation - every other entry/exit/
  filter field is byte-identical to the parent's, proven directly by
  `test_D_all_other_canonical_fields_unchanged`;
- the new candidate's `strategy_fingerprint` is proven identical to what
  #169A already computed as `proposal.novelty_fingerprint`
  (`test_G_fingerprint_matches_proposal_novelty_fingerprint`);
- status starts `EXPLORING` (never `PROMOTION_READY`, never approved) -
  `candidate_research_only` in the release check;
- added to the mission via the EXISTING `add_candidate`/
  `set_active_candidate` functions - the exact same functions every other
  candidate-creation path in this codebase already uses;
- idempotent: a repeated call against a mission that already has a
  candidate with this `strategy_fingerprint` is a safe no-op
  (`test_J_idempotent_second_call_on_updated_mission_is_noop`).

**No validation/backtest/robustness logic of any kind lives in this
module.** Once the candidate is added and the mission's `blocked_reason` is
cleared (status returns to `ACTIVE`), the EXISTING mission-driven cycle -
the SAME `LLMConversationBrain._try_mission_driven_research_cycle`/
`_try_candidate_robustness_cycle` every other candidate already goes
through, already reused by `AutonomousResearchRuntimeWorker.tick()` on
every non-BLOCKED tick - validates it. This hotfix adds zero new
validation/backtest/robustness code.

## 5. Production Strategy Never Touched

`StrategyCandidateRecord` is JSON-encoded inside `ResearchMission.
candidates` - a research-only entity, structurally separate from any live/
production strategy object. Neither `bounded_hypothesis_generation.py` nor
`proposal_candidate_bridge.py` imports `gaon.adapters.trading`,
`strategy_execution`, `strategy_deployment`, `champion_registry`,
`promotion_gate`, or `human_gated_promotion` - verified by static source
scan in both modules' own release checks and dedicated unit tests.

## 6. Existing Web Approval Workflow - Reused, Not Reinvented

`gaon.runtime.web_api._handle_candidates_list`/`_handle_mission_status` are
generic, `session_ref`-keyed read endpoints already used for every
candidate/mission regardless of how it was created. #169D-F introduces
**zero new endpoints**. The only change to `web_api.py` is adding
`hypothesis_summary` (and `parent_candidate_id`) to the already-existing
`_candidate_payload` - a one-line addition exposing a safe, structured
summary string (built solely from the changed field name and old/proposed
value - see `proposal_candidate_bridge.create_candidate_from_proposal`),
never raw external evidence text.

**Architectural note discovered during implementation**: a Web-originated
conversation (`GaonWebChatAdapter`, session id `web:{session_ref}`) and a
Telegram-originated one (`TelegramConversationAgent`, session id
`telegram:{chat_id}`) are separate session namespaces by existing,
pre-#169D-F design - `GaonWebChatAdapter.mission_for` only ever reads
`web:`-prefixed sessions. The autonomous research worker advances the
`telegram:{chat_id}`-scoped mission (matching every other autonomous-
research hotfix before this one). The release check and acceptance test
therefore prove what is actually true and useful: the SAME read endpoints,
given a mission in the same shape a real Web-originated conversation
already stores, correctly render an autonomously-created candidate and the
`AWAITING_HUMAN_APPROVAL` state - the payload contract and approval model
are fully shared; cross-source mission visibility (making one physical
mission simultaneously reachable from both a Telegram and a Web session
key) is a pre-existing characteristic of this codebase, not something
#169D-F changed or needed to change to satisfy its own safety contract.

Approval itself remains an existing, human-initiated conversational action
(via `record_promotion_candidate`, already called by the existing
robustness cycle) - #169D-F never calls it, never simulates it outside a
release check/test, and never bypasses it.

## 7. Approval Does Not Mean Apply

Unchanged: `MissionStatus.AWAITING_HUMAN_APPROVAL` (APPROVED-equivalent) is
structurally separate from any APPLY/ACTIVE/deploy state.
`AutonomousResearchRuntimeWorker.tick()`'s existing top-level check
(`mission.status in (AWAITING_HUMAN_APPROVAL, COMPLETED, CANCELLED)`) still
hard-stops before this hotfix's new chain, or any other progression, can
run - `approval_required=True, autonomous_progression=False` is now
explicitly reported on that exact return, per Section 12's observability
requirement. This hotfix adds no apply/deploy code path at all.

## 8. #169F: Autonomous Scheduler Wiring

`AutonomousResearchRuntimeWorker._plan_research_direction` (#168's own
hook point) is extended, not replaced: on a NEWLY-encountered direction it
behaves exactly as before (`research_direction_planned`, no further
progression that tick). On a direction observed AGAIN on a later tick, it
now calls `_advance_evidence_mutation_chain`, which advances EXACTLY one
stage per tick:

```
tick N:   research_direction_planned          (#168, unchanged)
tick N+1: direction_evidence_acquired          (#169B)
tick N+2: policy_decision_created              (#169C)
tick N+3: bounded_hypothesis_created           (#169D)
tick N+4: candidate_created                    (#169E - mission returns to ACTIVE)
tick N+5: cycle_executed                       (existing validation cycle, unchanged)
```

verified directly, action-by-action, by
`test_A_full_chain_progresses_direction_to_candidate`. Every stage first
checks the durable repository (`list_for_direction`) before creating
anything - a repeated tick against unchanged state is a cheap read, never
a duplicate row (`test_C_repeated_ticks_over_unchanged_state_are_
idempotent`). No second scheduler was created - the existing
`ScheduledJobRepository`/`AutonomousResearchRuntimeService` machinery is
completely unchanged.

**Bounded retry, not an infinite factory**: if the new candidate is later
rejected by the existing validation cycle, that rejection reshapes the
mission's candidate history, which changes `mission_history_fingerprint`
(#168) and therefore produces a genuinely NEW `ResearchDirection`/
`FailureAnalysis` fingerprint - #169D-F's chain re-engages naturally for
that new direction, exactly the "bounded retry / new proposal if budget
remains" behavior requested, entirely for free from #168's own existing
fingerprinting design (`test_I_rejected_candidate_allows_another_bounded_
proposal_if_budget_remains`). This is genuinely bounded: `#169A`'s
`_next_historical_value` only ever moves one step up a small, finite
historical grid, so repeated retries terminate honestly
(`hypothesis_value_space_exhausted`) once the grid is exhausted - never an
unbounded loop.

## 9. Observability

`AutonomousResearchTickResult` gained new fields
(`evidence_acquisition_id`, `policy_decision_id`, `policy_status`,
`proposal_id`, `candidate_id`, `changed_dimension`, `mutation_direction`,
`approval_required`, `autonomous_progression`), populated only on the
specific action that produced them - every value is a structured id/enum/
field name already durably persisted by the call that produced it, never
raw evidence text, never a secret.

## 10. Persistence: Schema v41 -> v42

One new, additive table: `research_hypothesis_execution_lineage`
(`proposal_id` PK, `session_ref`, `mission_id`, `research_direction_id`,
`evidence_acquisition_id`, `policy_decision_id`, `candidate_id` nullable,
timestamps). **Why a new table was actually necessary** (not merely
convenient): neither `BoundedHypothesisProposal` (#169A) nor any existing
table records the cross-reference from a proposal back to the evidence
acquisition/policy decision that authorized it, or forward to the
candidate #169E creates from it - and #169A's own schema was deliberately
left unmodified per this hotfix's scope (see Section 12). No existing
table's data is duplicated - this table stores only the missing cross-
references plus the one genuinely new fact (`candidate_id`).

`_upgrade_v41_to_v42` is additive-only, idempotent (`CREATE TABLE/INDEX IF
NOT EXISTS`), and preserves #170's migration-ownership contract exactly
(unchanged: single owner, `gaon-web` non-owner fail-closed, explicit
bounded `busy_timeout`, WAL still disabled). `direction_evidence.py`'s and
`evidence_mutation_policy.py`'s own release checks now compare against the
live `SCHEMA_VERSION` import (a fix made during #169C) rather than a
hardcoded literal, so this bump did not require touching their logic - only
`sqlite_lock.py`'s and four existing tests' hardcoded version literals
needed a one-line bump (39/40/41 -> 42 was already this repository's
established, accepted maintenance pattern across every prior hotfix in
this chain).

## 11. Idempotency & Fingerprints

Every new durable write in this chain is keyed by a deterministic
fingerprint derived from already-durable ids (`direction.fingerprint`,
`analysis.fingerprint`, `evidence.fingerprint`, `decision.fingerprint`,
`proposal.novelty_fingerprint`) - never a random id, never wall-clock. No
step of #169D-F introduces a new idempotency mechanism; each reuses the
convention #168/#169A/#169B/#169C already established.

## 12. Authority Boundary

Static `inspect.getsource()` scans (matching the #165/#168/#169A/#169B/
#169C convention) in every new module's own release check AND in dedicated
unit tests prove zero imports of `gaon.adapters.trading`,
`strategy_execution`, `strategy_deployment`, `champion_registry`,
`promotion_gate`, `human_gated_promotion` from `bounded_hypothesis_
generation.py`, `proposal_candidate_bridge.py`, or the new wiring inside
`autonomous_research_runtime.py`. `#169D` never calls `generate_bounded_
proposals` with a caller-supplied value; `#169E` never calls a backtest/
validation function directly; `#169F` never calls anything beyond the
functions this doc already names.

## 13. No LLM

No LLM/embedding/free-text-interpretation call anywhere in
`bounded_hypothesis_generation.py`, `proposal_candidate_bridge.py`, or the
new `_advance_evidence_mutation_chain` code. Every dimension, direction,
and value is either a hardcoded #169A/#169C constant or a deterministic
function of already-persisted historical template values.

## 14. Deployment Procedure (schema v42)

Follows #170's existing Safe Deployment Procedure exactly (stop both
services, backup + `quick_check`, migrate once via the owner path, verify
`schema_version == 42`, start both services, verify health). No deploy was
performed as part of this hotfix.

## Known Limitations

- `generate_bounded_proposals`'s own parent-selection (`next(candidate for
  candidate in candidate_history if candidate.candidate_id in
  evidence_candidate_ids ...)`, unchanged #169A code) picks the FIRST
  matching terminal candidate in insertion order, not necessarily the most
  recently rejected one. In practice this means a genuinely NEW direction
  (Section 8) reliably produces at most one further candidate before its
  own single mapped dimension (`breakout_lookback`) is exhausted or the
  proposal becomes a `DUPLICATE` - a safe, honest, but conservative
  retry depth, not a full multi-step grid walk across many generations in
  one direction's lifetime. Widening this would require reviewing/changing
  #169A's own parent-selection logic, explicitly out of this hotfix's
  scope (`hypothesis_proposal.py` was left unmodified).
- Cross-source (Telegram <-> Web) live mission mirroring does not exist in
  this codebase today (Section 6) - not a gap #169D-F introduced or was
  asked to close.
- Reaching `MissionStatus.AWAITING_HUMAN_APPROVAL` still requires the
  mission's OWN `target_promotion_ready_candidates` count of DISTINCT
  verified strategies (existing #168-era semantics, unchanged) - a single
  #169E-created candidate alone does not trigger approval unless it is the
  last one needed.
