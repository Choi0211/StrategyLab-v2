# Hotfix #169B: Candidate-Independent Evidence Acquisition

Status: Implemented (backend only). Current flow:

```
ResearchDirection -> deterministic bounded ResearchQuestion
                   -> existing production AutonomousExternalResearchExecutor
                   -> normalized, durable direction-level evidence
                   -> requirement satisfaction state
```

Not present (deliberately out of scope for this hotfix): any
evidence-to-mutation policy, `BoundedHypothesisProposal` mutation,
`StrategyCandidateRecord` creation, backtest/validation execution,
scheduler/autonomous runtime wiring, Champion promotion, approval bypass,
production strategy apply, trading/orders, or risk/leverage change.

## Purpose

The #169B investigation found that `gaon.knowledge.external_research_execution.
AutonomousExternalResearchExecutor` already runs a fully candidate-independent
evidence pipeline (`existing_candidates=()` is a genuine, working default -
not an aspirational one), but nothing in the repository could turn a
`ResearchDirection` (#168) into the `ResearchQuestion` that executor requires,
and nothing gave the resulting evidence a durable home tied back to the
direction/mission/session that produced it (the existing
`ExternalResearchMemoryStore` is file-based JSON, with no direction/mission/
session lineage columns to SQL-join against). `gaon.research.direction_evidence`
builds exactly those two missing pieces, and nothing more.

## Architecture

```
ResearchDirection + FailureAnalysis (#168, unmodified)
        |
        v
build_research_question()          <- the ONLY new query-generation logic
        |                              (deterministic, human-authored,
        |                               structured-fields-only)
        v
AutonomousExternalResearchExecutor  <- REUSED AS-IS, zero modification
        |                              (gaon.knowledge.external_research_execution)
        v
acquire_direction_evidence()        <- maps the executor's own terminal
        |                              state to a #169B requirement state,
        |                              honestly, never optimistically
        v
DirectionEvidenceAcquisition        <- durable, direction-level record
        |
        v
DirectionEvidenceRepository          <- SQLite, schema v40, additive,
                                         idempotent on (session_ref, fingerprint)
```

`#169A` (`gaon.research.hypothesis_proposal`) is untouched - #169B does not
read from it, write to it, or change its status model. Evidence in #169B is
owned at the `ResearchDirection` level, not the `BoundedHypothesisProposal`
level, matching the #169B investigation's finding that evidence is a property
of a *research direction* (what should be investigated), not of any one
proposed mutation.

## Reuse, Not Reinvention

Every piece of the actual research pipeline - discovery planning and
execution (Crossref/DataCite), academic relevance screening, DOI/content
resolution, bounded content acquisition, safe normalization, claim
extraction, and conflict re-evaluation - is
`AutonomousExternalResearchExecutor` and its collaborators, completely
unmodified. `gaon.research.direction_evidence.build_production_executor`
constructs that executor using exactly the same `PRODUCTION_EXTERNAL_*`
budget constants, host allowlist, and provider wiring that
`gaon.knowledge.telegram_autonomous_learning._run_production_external_research`
(the existing candidate-bound production entrypoint) already uses - no new
budget numbers, no new provider, no new host allowlist were introduced.

## Direction -> ResearchQuestion Mapping (the only new query-generation logic)

`build_research_question` is a small, versioned, human-authored mapping -
never an LLM, never free-text query generation, never a fallback query for
an unmapped failure class. It is intentionally conservative: only
`FailureClass.COST_SLIPPAGE_FRAGILITY` is mapped in this hotfix, matching the
only failure class #168/#169A's mission-history classifier actually produces
in production today. Any other failure class returns
`OverallAcquisitionState.UNSUPPORTED` from `acquire_direction_evidence` -
honestly, with zero requirement results, never a fabricated question.

The mapping reads only structured fields
(`FailureAnalysis.dominant_failure_class`, the fixed
`EvidenceRequirementComponent.component_id`, and `ResearchDirection.fingerprint`
for id derivation). `ResearchDirection.rationale` (free-form prose, itself
partially derived from evidence text upstream) is never read by this
function - a unit test (`test_C_rationale_never_used_as_query`) proves
injecting adversarial text into `rationale` has zero effect on the generated
query.

## Evidence Requirement Decomposition: Academic vs. Operational

The real, current production `evidence_requirements` text for
`cost_slippage_fragility` (`gaon.research.research_direction._EVIDENCE_REQUIREMENTS`)
is: *"transaction-cost/slippage sensitivity evidence, and confirmation the
cost model matches live execution."* #169B decomposes this into two
structurally different components:

| component | kind | can #169B satisfy it? |
|---|---|---|
| `transaction_cost_slippage_sensitivity` | `ACADEMIC_EXTERNAL` | Yes - routed through the real executor |
| `cost_model_matches_live_execution` | `OPERATIONAL_LIVE_EXECUTION` | **No, structurally** - always `REQUIRES_OPERATIONAL_EVIDENCE` |

The second component can never be satisfied at the candidate-independent
stage: "confirmation the cost model matches live execution" requires
telemetry from an already-live-traded candidate, which by definition does
not exist yet. #169B never routes this component through the external
research executor at all - it is a pure, unconditional
`REQUIRES_OPERATIONAL_EVIDENCE` regardless of whether an executor is even
supplied. It is never satisfied by substituting an academic paper for live
telemetry.

## Requirement and Overall State Vocabulary

```
RequirementSatisfactionState: PENDING, ACQUIRED, PARTIAL, UNMET_REQUIREMENT,
    PROVIDER_NOT_CONFIGURED, REQUIRES_OPERATIONAL_EVIDENCE,
    FAILED_RETRYABLE, FAILED_TERMINAL

OverallAcquisitionState: ACQUIRED, PARTIAL, UNMET, UNSUPPORTED
```

`_academic_requirement_state` is an exhaustive, conservative mapping from
every `ExternalResearchTerminalState` the (unmodified) executor can return -
never promoting "no evidence" to "acquired." One honest, verified nuance:
the reused, unmodified `gaon.knowledge.conflicts.KnowledgeConflictDetector`
requires **two independent supporting sources** before a topic is considered
free of an "insufficient independence" gap; a single real, successfully
acquired source therefore lands the executor on
`ExternalResearchTerminalState.UNRESOLVED_CONFLICT`, which #169B maps to
`RequirementSatisfactionState.PARTIAL` (real evidence found, genuinely
processed end to end, but not yet independently corroborated) rather than
`ACQUIRED`. This is the existing, unmodified executor's own evidentiary
standard - out of #169B's scope to relax (see "Reuse, Not Reinvention"
above) - and it is reflected honestly rather than overridden.

`_aggregate_overall_state`: `ACQUIRED` only if every component is
`ACQUIRED`; `UNMET` only if every component is in the "nothing achieved" set
(`PENDING`, `UNMET_REQUIREMENT`, `PROVIDER_NOT_CONFIGURED`, `FAILED_TERMINAL`,
`REQUIRES_OPERATIONAL_EVIDENCE`); otherwise `PARTIAL`. For
`cost_slippage_fragility`, the operational component is always in the
"nothing achieved" set, so the overall state is **never** `ACQUIRED` -
verified directly by both the unit and integration test suites, across every
provider outcome (evidence found, provider unavailable, zero results).

## Provider Honesty

`executor=None` (no external research provider configured for this call) is
treated as an honest `PROVIDER_NOT_CONFIGURED` for the academic component -
never silently skipped, never fabricated as satisfied. A network-disabled
executor maps to the same state via the executor's own
`ExecutionFailureKind.NETWORK_DISABLED` classification. Zero discovery
results map to `UNMET_REQUIREMENT`. A budget-exhaustion or transient-failure
terminal state maps to `FAILED_RETRYABLE`; a structural data failure maps to
`FAILED_TERMINAL`. "No evidence" is never promoted to "acquired" anywhere in
this mapping.

## Untrusted Evidence Boundary

Every external string this module ever touches (title, abstract, DOI, URL,
publisher) flows through the executor's existing, unmodified
`external_content_policy == "evidence-not-instruction"` invariant. #169B
adds no new LLM call and no new text-interpretation step. A
`DirectionEvidenceAcquisition` record carries only structured counts,
states, and provenance/query fingerprints - never a raw evidence string as
an executable field. `gaon.research.direction_evidence` never imports
`gaon.adapters.trading`, `gaon.adapters.strategy_execution`,
`gaon.adapters.strategy_deployment`, `gaon.adapters.champion_registry`,
`gaon.knowledge.promotion_gate`, or `gaon.knowledge.human_gated_promotion` -
verified by a static `inspect.getsource()` source scan in both this
module's own release check and a dedicated unit test
(`AuthorityBoundaryTests.test_T_module_never_imports_authority_modules`).

**Evidence is not instruction. Evidence is not strategy mutation. Evidence
is not a candidate. Evidence is not an approval. Evidence is not an order.**

## Durable Persistence (schema v40)

`research_direction_evidence` is a single, additive aggregate table (schema
v39 -> v40, `gaon.runtime.migrations._upgrade_v39_to_v40`) carrying full
lineage (`session_ref`, `mission_id`, `research_direction_id`,
`failure_analysis_id`), the question/query fingerprint, requirement results
as JSON, overall state, and timestamps. Idempotency uses a
`(session_ref, fingerprint)` unique index and `INSERT OR IGNORE` - the same
session-scoped-fingerprint convention `research_hypothesis_proposals`
(#169A) already established, deliberately chosen over a bare fingerprint
index to avoid cross-session fingerprint collisions.
`DirectionEvidenceAcquisition.evidence_acquisition_id` itself also
incorporates `session_ref` (not just the repository's unique index), so two
different sessions that happen to reach an identical direction/analysis
fingerprint still get distinct primary keys.

This hotfix preserves #170's migration-ownership contract exactly:
`strategylab-gaon` remains the sole migration owner
(`RuntimeStateStore(path)`, `owns_migration=True` default); `gaon-web-serve`
remains a non-owner that only performs the existing read-only
`check_schema_version_compatible` check and fails closed on any mismatch.
Neither behavior was touched by this hotfix.

## Bounded Execution

`build_production_executor` passes through exactly the same
`PRODUCTION_EXTERNAL_*` budgets `_run_production_external_research` already
uses (`max_provider_calls`, `max_sources`, `max_relevant_candidates`,
`max_resolution_attempts`, `max_content_acquisition_attempts`,
`max_acquired_sources`, `max_grounded_sources`, `max_total_download_bytes`,
the content host allowlist). #169B's adapter introduces no new numbers and
never grants a wider budget than the reused executor's own bounds.

## Fixture/Production Separation

The release check (`production_candidate_independent_evidence_release_check`)
and this hotfix's own test suites use small, local, deterministic fixture
transports (`_FixtureCrossrefTransport`, `_FixtureDoiResolutionTransport`,
`_FixtureContentTransport`) - never real internet traffic, and never the
private fixture classes from `gaon.knowledge.telegram_autonomous_learning`'s
own release-check scenarios (kept independent to avoid coupling). Every
fixture path uses an explicit temporary `GaonStorage` root and a throwaway
in-memory/temp-file SQLite database - never the real production data root or
the shared `runtime.sqlite`. A production caller (a future CLI command, or
#169F's autonomous wiring) that omits every `*_transport` argument gets the
executor's real, unmodified HTTPS transports.

## #169A Impact

None. `gaon.research.hypothesis_proposal` is not imported by, not modified
by, and not read from by `gaon.research.direction_evidence`. #169A's own
release check (`production_bounded_hypothesis_proposal_release_check`) was
re-run after this hotfix's schema bump and still passes unchanged.

## No Autonomous Wiring

`gaon.research.direction_evidence` is never called from
`autonomous_research_runtime.py`'s scheduler/tick, and there is no durable
scheduler job or system-turn wiring anywhere in this hotfix. This hotfix
builds capability only; actual orchestration is deferred to a future #169F.

## Responsibility Handoff

- **#169C** - normalized evidence -> allowed mutation concept/policy (what,
  if anything, a `DirectionEvidenceAcquisition` is permitted to influence
  about a future `BoundedHypothesisProposal`'s mutation choice).
- **#169D** - bounded, evidence-grounded hypothesis generation.
- **#169E** - proposal/candidate/validation pipeline wiring.
- **#169F** - autonomous scheduler/runtime wiring (when and how
  `acquire_direction_evidence` actually gets called during a live mission
  tick, and under what rate/idempotency policy).

None of these are implemented by #169B.

## Known Limitations

- Given the reused, unmodified `KnowledgeConflictDetector`'s two-independent-
  source bar, the academic component realistically lands on `PARTIAL` (not
  `ACQUIRED`) for any single-source real acquisition - a property of the
  reused executor, not a #169B shortcoming. This does not affect the
  overall-state acceptance criterion (never a bare `ACQUIRED` for
  `cost_slippage_fragility`), since both `ACQUIRED` and `PARTIAL` academic
  outcomes still combine with the operational component's permanent
  `REQUIRES_OPERATIONAL_EVIDENCE` to produce `PARTIAL` overall.
- Only `FailureClass.COST_SLIPPAGE_FRAGILITY` has a research-question
  mapping. Every other failure class is honestly `UNSUPPORTED` until a
  future hotfix adds a reviewed, human-authored mapping for it.
- No re-acquisition/refresh policy exists yet (deliberately deferred - no
  scheduler exists yet to drive one). A caller that wants updated evidence
  today must construct a new `ResearchDirection` (a new fingerprint) rather
  than relying on an automatic refresh.
- No `READY_FOR_EVIDENCE` Proposal-level link exists yet - deferred to a
  future #169C/#169E, per the Responsibility Handoff above.

## Safe Deployment Procedure

Schema bumped v39 -> v40 (additive only - one new table, no existing table
touched). This deploy must follow #170's existing Safe Deployment Procedure
(`docs/architecture/ProductionSQLiteLockStability.md`) exactly:

1. `systemctl stop strategylab-gaon`
2. `systemctl stop gaon-web`
3. Backup the database and confirm `PRAGMA quick_check = ok`.
4. Migrate once, explicitly, via the migration owner's path (e.g.
   `python -m gaon.runtime.cli db-check --db /var/lib/strategylab/gaon-runtime.sqlite`).
5. Verify the reported `schema_version` is `40`.
6. `systemctl start strategylab-gaon`
7. `systemctl start gaon-web`
8. Verify health (`db-check`/`health` CLI, and `gaon-web`'s own health
   endpoint) on both services.

No deploy was performed as part of this hotfix - implementation, tests, and
documentation only.
