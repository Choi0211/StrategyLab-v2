# Gaon V1/V2 Asset Reuse Audit

Status: COMPLETE  
Branch: `audit/gaon-v1-v2-final-integration`  
Schema: v36 unchanged  
Verdict: `GAON V1/V2 INTEGRATION COMPLETE`

## Purpose

This final closeout audit verifies that Gaon V2 production behavior reuses or
intentionally replaces the public StrategyLab V1 assets without silently
forking engines, leaking legacy fixture paths, weakening safety gates, or
depending on private MyMoneyGuard runtime code.

This is not a new research sprint. The audit adds deterministic release checks
and documentation only.

## Classification

- `REUSED_DIRECTLY`: V2 uses the same public asset without material extension.
- `REUSED_AND_EXTENDED`: V2 uses the V1 contract or engine and extends it.
- `REPLACED_INTENTIONALLY`: V2 deliberately does not reuse the asset for safety
  or public-repository reasons.
- `DUPLICATED_UNNECESSARILY`: overlapping implementation should be removed.
- `LEGACY_UNUSED`: retained compatibility code not in production path.
- `MISSING_FROM_V2`: V1 capability required for production but absent.
- `NOT_APPLICABLE`: outside Gaon V2 production scope.

## Asset Matrix

| V1 Asset | V2 Implementation | Production Call Path | Status | Action |
| --- | --- | --- | --- | --- |
| Market data acquisition and normalization | `YahooKRXHistoricalDataProvider`, `KRXDatasetBuilder` | Telegram -> autonomous learning -> `krx_real_research_payload` -> dataset builder | `REUSED_AND_EXTENDED` | None |
| KRX universe selection | `KRXUniverseSelector` | multi-symbol research -> canonical symbol universe -> per-symbol real research | `REUSED_AND_EXTENDED` | None |
| Backtest execution engine | `RuleBasedBacktestEngine` | real research payload -> `RealAutonomousResearchPipeline` -> rule engine | `REUSED_AND_EXTENDED` | None |
| Strategy representation and breakout rules | `CanonicalStrategySpec`, `UserStrategyParser`, `StrategyResearchExperiment` | request parsing -> canonical fingerprint -> candidate experiment | `REUSED_AND_EXTENDED` | None |
| Cost/slippage assumptions | `BacktestExecutionAssumptionSet`, transaction-cost stress | backtest assumptions -> validation stress -> robustness report | `REUSED_AND_EXTENDED` | None |
| Performance metrics | `PerformanceMetricsCalculator`, `RealPerformanceMetrics` | backtest result -> authoritative metric renderer | `REUSED_AND_EXTENDED` | None |
| Validation and robustness | `AutonomousValidationLoopV2`, production robustness execution | candidate backtest -> validation evidence -> robustness/tournament | `REUSED_AND_EXTENDED` | None |
| Research memory and learning knowledge | `SQLiteResearchMemoryRepository`, external research memory | autonomous learning -> evidence-backed memory -> learning summary | `REUSED_AND_EXTENDED` | None |
| Evidence and provenance | multi-source research and safe acquisition | discovery -> acquisition -> normalization -> claims -> hypotheses | `REUSED_AND_EXTENDED` | None |
| Candidate, tournament, and ranking | `StrategyRobustnessRanker`, candidate ranking | hypothesis -> experiment -> validation -> tournament | `REUSED_AND_EXTENDED` | None |
| Approval, Champion replacement, rollback | Champion registry and two-stage approval checks | promotion readiness -> freeze -> Stage 2 approval -> Champion/rollback | `REUSED_AND_EXTENDED` | None |
| Telegram and conversation routing | `TelegramConversationAgent`, `LLMConversationBrain`, `SafeToolExecutor` | update -> read-only routing -> safe tool -> authoritative renderer | `REUSED_AND_EXTENDED` | None |
| SQLite persistence and audit history | `RuntimeStateStore`, repositories, tool audit, durable events | runtime store -> repositories -> release checks | `REUSED_AND_EXTENDED` | None |
| Live MyMoneyGuard/KIS execution adapters | Public contracts only; private runtime excluded | Not in Gaon V2 public production path | `REPLACED_INTENTIONALLY` | None |

No asset is classified as `DUPLICATED_UNNECESSARILY` or `MISSING_FROM_V2`.

## Production Authoritative Call Path

```text
Telegram update
-> TelegramConversationAgent
-> LLMConversationBrain
-> route_read_only_tool
-> SafeToolExecutor
-> autonomous_learning_research
-> telegram_autonomous_learning_payload
-> krx_real_research_payload
-> build_market_data_provider_from_env
-> YahooKRXHistoricalDataProvider
-> KRXDatasetBuilder
-> RuleBasedBacktestEngine
-> PerformanceMetricsCalculator
-> autonomous_quant_partner_payload
-> grounded external evidence and hypotheses
-> StrategyResearchExperiment
-> AutonomousValidationLoopV2
-> StrategyRobustnessRanker
-> PromotionCandidateGate
-> Stage 1 candidate freeze
-> Stage 2 Champion approval
-> ChampionRegistryService
-> rollback support
```

Fixture release adapters, deterministic discovery transports, and fixture
backtests are not part of the production Telegram call path.

## Duplicate And Legacy Findings

- No unintended duplicate production backtest engine was found. Production
  KRX research uses `RuleBasedBacktestEngine`.
- Legacy fixture adapters remain for deterministic tests and release checks.
  They are intentionally isolated from production Telegram execution.
- Private MyMoneyGuard/KIS live execution assets remain intentionally excluded
  from this public repository.

## Research Memory Continuity

V1 learning-memory fixtures and repository contracts remain readable. V2
extends them with evidence-backed external research memory, closed-loop
learning summaries, and context-preserving Telegram follow-ups. Memory can
inform research, but it cannot approve promotion or mutate strategy state.

## Final Status

- `V1_ASSET_REUSE_STATUS=complete`
- `V1_RESEARCH_MEMORY_STATUS=continuous`
- `DUPLICATE_ENGINE_STATUS=no_unintended_duplicate_engine`
- `LEGACY_PATH_STATUS=isolated`
- `PRODUCTION_AUTHORITATIVE_PATH_STATUS=complete`

## Release Checks

```bash
python -m gaon.runtime.cli gaon-production-v1-asset-reuse-audit-release-check
python -m gaon.runtime.cli gaon-production-v1-v2-authoritative-path-release-check
python -m gaon.runtime.cli gaon-production-no-unintended-duplicate-engine-release-check
python -m gaon.runtime.cli gaon-production-research-memory-continuity-release-check
python -m gaon.runtime.cli gaon-production-legacy-path-isolation-release-check
python -m gaon.runtime.cli gaon-production-v1-v2-final-integration-release-check
```

## Safety

- No live trading.
- No KIS/Broker order.
- No automatic Champion promotion.
- No approval bypass.
- No strategy mutation.
- No fixture-backed production promotion.
- No fabricated metrics or evidence.
- No private MyMoneyGuard dependency.
