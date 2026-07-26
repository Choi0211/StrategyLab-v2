# Sprint 121-130 Research Operations

Status: Implemented  
Schema: v34

## Goal

Sprint 121-130 extends Gaon from a backtest-result reporter into an approval-gated research operations system.

The pipeline remains evidence-first:

1. Research Quality Gate
2. Statistical Confidence
3. Candidate Dominance Analyzer
4. Research Period Policy
5. Automatic Re-test / Period Expansion recommendation
6. Champion / Challenger Evaluation
7. Promotion Recommendation Policy
8. Human Approval Gate
9. Approved Strategy Configuration Change
10. Rollback / Audit / Telegram Strategy Change Report foundation

## Boundaries

- No live trading
- No KIS order
- No broker order
- No automatic Champion promotion
- No configuration change before explicit human approval
- No private repository dependency
- No arbitrary shell or SQL expansion

## Architecture

`gaon.research.operations` owns the deterministic research operations contracts:

- `BacktestEvidence`
- `ResearchQualityGate`
- `StatisticalConfidence`
- `CandidateDominance`
- `ResearchPeriodPlan`
- `PromotionRecommendation`
- `StrategyConfigVersion`
- `ResearchOperationReport`
- `ResearchOperationsService`
- `SQLiteResearchOperationRepository`

The service can analyze structured champion/challenger evidence, recommend a challenger only when quality/confidence/dominance pass, apply a strategy configuration only after explicit approval, and roll back to the previous approved configuration.

## Database

Schema v34 adds:

- `research_operation_reports`
- `research_config_approvals`
- `strategy_config_versions`
- `strategy_config_audit`

All configuration mutations write audit records and preserve rollback references.

## CLI

- `research-ops-demo`
- `research-ops-release-check`
- `research-config-approve`
- `research-config-rollback`
- `research-ops-report`
- `research-ops-cleanup`

## Safe Tools

`research_operation_status` is read-only. It exposes recent operation reports, active strategy config metadata, and audit count. It excludes release-check/demo/test artifacts by default and cannot approve, apply, roll back, trade, or promote.

## Hotfix 130.1 State Isolation

Release-check and demo fixtures are treated as non-production artifacts. The
reserved identifiers are `research-ops-release-check:*`,
`research-recommendation:research-ops-release-check:*`, `research-ops-demo:*`,
and `research-recommendation:research-ops-demo:*`.

`research-ops-release-check --db <production-db>` opens the target DB only for
schema/state verification, then runs fixture writes in an isolated in-memory
runtime store. The command fails if production research operation table counts
change during the check.

`research-ops-demo` is isolated by default. Use `--persist` only for local
diagnostics. Persisted demo artifacts remain hidden from normal status output
and can be removed with:

```bash
python -m gaon.runtime.cli research-ops-cleanup --db /var/lib/strategylab/gaon-runtime.sqlite --dry-run
python -m gaon.runtime.cli research-ops-cleanup --db /var/lib/strategylab/gaon-runtime.sqlite --apply
```

Cleanup deletes only release-check/demo/test artifacts and appends an
`artifact_cleanup` audit record. Real user research reports and approved configs
are preserved.

## Known Limitations

- The release-check uses deterministic fixture evidence.
- Automatic re-test currently emits an expanded-period plan; it does not perform an external live-market re-fetch in this sprint.
- Telegram strategy-change reporting is represented by deterministic report text and read-only status tooling; no live Telegram write command is added for configuration mutation.
