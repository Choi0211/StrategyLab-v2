# Sprint 131-140 Autonomous Retest Pipeline

Status: Implemented  
Schema: v35

## Goal

Sprint 131-140 extends Gaon from one-shot real KRX research into an
evidence-first retest workflow. When an initial research result has insufficient
sample size, Gaon can plan deterministic period expansion, re-fetch market data,
re-run the same strategy and execution assumptions, re-evaluate tested
candidates, refresh the advisory recommendation, and store the evidence lineage.

## Architecture

`gaon.research.autonomous_retest` owns the Sprint 131-140 contracts:

- `RetestDecision`
- `ResearchPeriodStep`
- `RetestEvidence`
- `AutonomousRetestRun`
- `RetestTriggerEngine`
- `AdaptiveResearchPeriodPlanner`
- `RetestStopPolicy`
- `AutonomousRetestOrchestrator`
- `SQLiteAutonomousRetestRepository`

The orchestrator reuses the existing KRX real-research contracts:

- `CanonicalStrategySpec`
- `BacktestExecutionAssumptionSet`
- `RuleBasedBacktestEngine`
- `RealBacktestResult`
- `DataQualityReport`
- `ImprovementCandidate`

## Retest Policy

Retest is required when the structured evidence has insufficient sample size or
the quality gate indicates `needs_retest`. High return alone cannot skip a
retest. The default deterministic expansion sequence is:

1. 6 months
2. 18 months
3. 3 years
4. 5 years

When a user explicitly bounds the research period, the planner records
`user_period_boundary` and does not silently expand beyond it.

## Stop Policy

The retest loop stops on:

- `min_trades_reached`
- `max_period_reached`
- `data_availability_limit`
- `blocking_data_quality`
- `provider_failure`
- `no_additional_evidence`
- `user_period_boundary`

Low trade counts also cap confidence and mark win rate / profit factor as
unreliable when the sample is too small.

## Database

Schema v35 adds:

- `research_retest_runs`
- `research_retest_evidence`
- `research_period_plans`

These tables store run status, period lineage, structured retest evidence, and
final advisory recommendation. They do not store approvals or applied strategy
configuration.

## CLI

- `research-retest-demo`
- `autonomous-retest-release-check`
- `research-retest-status`
- `research-retest-history`

## Safe Tools

- `research_retest_status`
- `research_retest_history`

Both are read-only. They cannot approve, apply, roll back, trade, promote a
Champion, or mutate Telegram configuration.

## Release Check

`autonomous-retest-release-check` verifies:

- initial trade count is insufficient
- deterministic period expansion reaches the minimum sample
- strategy fingerprint remains stable
- execution assumptions fingerprint remains stable
- provider provenance is `source=real`
- `fixture_backed=false`
- period lineage is preserved
- final recommendation is advisory only
- no approval, config apply, Champion promotion, or trading occurs
- target production retest tables remain unchanged; fixture writes run in an
  isolated in-memory store

## Known Limitations

- The public release check uses a deterministic synthetic real-provenance
  provider to avoid live network dependency in CI.
- `research-retest-demo` is isolated by default. Use `--persist` only for local
  diagnostics; normal status/history tooling hides release-check/demo artifacts.
- Production real-data activation still depends on configured public KRX/Yahoo
  provider availability.
- Retest recommendations are advisory and require the existing Human Approval
  Gate before any strategy configuration change.
