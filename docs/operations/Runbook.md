# StrategyLab v2 Runbook

## Test

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src;tests/unit;tests/integration"
py -3.11 -m unittest discover -s tests/unit
py -3.11 -m unittest discover -s tests/integration
```

Linux/macOS bash:

```bash
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/unit
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/integration
```

## Release Verification

Windows PowerShell:

```powershell
py -3.11 scripts/verify_release.py
```

Linux/macOS bash:

```bash
python3.11 scripts/verify_release.py
```

## VPS Deployment Verification

Production deployments must refresh the editable package and verify the module
path before restarting the long-running service:

```bash
cd /opt/strategylab-v2
git pull origin main
.venv/bin/pip install -e .
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
sudo systemctl restart strategylab-gaon
sudo systemctl status strategylab-gaon
```

The import-path check must show `actual=/opt/strategylab-v2/src/gaon`. A
`.venv/lib/python*/site-packages/gaon` path means the VPS is running a stale
copied package and the service must not be treated as upgraded.

For final Gaon V2 conversation UX verification, run:

```bash
.venv/bin/python -m gaon.runtime.cli gaon-production-natural-research-conversation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-followup-context-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-no-unnecessary-research-rerun-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-natural-promotion-approval-conversation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-conversation-grounding-integrity-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-final-conversation-ux-release-check
```

The final aggregate must report `NATURAL_RESEARCH_RESPONSE=pass`,
`FOLLOWUP_CONTEXT=pass`, `UNNECESSARY_RERUN_BLOCKED=pass`,
`AUTHORITATIVE_GROUNDING=pass`, `TWO_STAGE_APPROVAL_PRESERVED=pass`,
`RESEARCH_ENGINE_REUSED=pass`, `DUPLICATE_CONVERSATION_ENGINE=false`, and
`safety=pass`.

For Autonomous Learning V2 production-loop verification, run:

```bash
.venv/bin/python -m gaon.runtime.cli gaon-production-relevant-academic-discovery-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-safe-doi-redirect-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-relevant-academic-content-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-academic-source-fallback-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-academic-source-budget-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-learning-state-semantics-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-academic-content-resolution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-learning-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-multi-source-research-contract-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-web-news-research-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-youtube-research-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-community-idea-research-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-evidence-fusion-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-source-independence-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-cross-source-conflict-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-multi-source-experiment-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-prompt-injection-safety-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-validation-sample-diagnostic-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-provider-registry-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-authoritative-source-acquisition-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-source-diversification-planner-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-counter-evidence-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-validation-sufficiency-v2-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-iterative-research-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-robust-strategy-validation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-strategy-tournament-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-learning-memory-closed-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-promotion-readiness-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-observability-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-quant-partner-acceptance-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-research-wiring-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-validation-coverage-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-horizon-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-sample-sufficiency-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-backtest-signal-diagnostic-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-validation-window-integrity-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-validation-coverage-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-no-fabricated-validation-metrics-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-multi-symbol-validation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-oos-validation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-walk-forward-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-regime-validation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-parameter-sensitivity-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-transaction-cost-stress-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-monte-carlo-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-robustness-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-multi-symbol-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-oos-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-walk-forward-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-regime-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-parameter-variant-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-cost-stress-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-trade-return-series-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-monte-carlo-execution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-multi-source-provider-state-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-evidence-provenance-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-research-action-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-budget-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-final-promotion-readiness-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-no-fabricated-research-results-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-sprint249-256-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-oos-evaluation-boundary-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-walk-forward-evaluation-boundary-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-oos-performance-comparison-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-walk-forward-performance-comparison-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-regime-classification-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-cost-stress-performance-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-peer-selection-policy-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-validation-execution-vs-result-status-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-candidate-freeze-integrity-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-no-evaluation-window-contamination-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-hotfix2561-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-final-autonomous-research-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-final-conversation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-two-stage-approval-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-candidate-freeze-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-champion-replacement-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-champion-rollback-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-final-safety-boundary-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-gaon-v2-completion-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-v1-asset-reuse-audit-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-v1-v2-authoritative-path-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-no-unintended-duplicate-engine-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-research-memory-continuity-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-legacy-path-isolation-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-v1-v2-final-integration-release-check
```

These checks verify strategy-specific academic relevance screening, rejection
of irrelevant non-financial papers, DOI redirect safety, academic DOI/resource
resolution, resilient fallback after an unavailable relevant source, bounded
source-attempt budgets, content-grounded evidence, evidence-backed hypotheses,
candidate experiment lineage, authoritative real candidate validation, robust
state semantics, multi-source provider contracts, source independence,
cross-source conflict detection, validation sample diagnostics, autonomous
source diversification, counter-evidence search, bounded iterative research,
robust strategy validation, candidate tournament ranking, learning-memory
closed-loop recording, promotion readiness, production observability,
production Telegram wiring after academic content exhaustion, and the human-only
promotion gate without mutating strategy configuration or placing orders. The
Hotfix 240.2 validation coverage checks additionally verify bounded research
horizon extension, real-data bar count propagation, warmup accounting, signal
diagnostics, sample sufficiency, and baseline/candidate validation-window
integrity.
Hotfix 248.1 robustness checks additionally verify that production-grade
robustness sections do not fabricate metrics when execution evidence is absent,
and that approval readiness requires actual multi-symbol, OOS, walk-forward,
regime, parameter, transaction-cost, and Monte Carlo execution lineage.
Sprint 249-256 real execution checks additionally verify that Autonomous Quant
Partner reconstructs authoritative real-research inputs and executes available
robustness validations through the existing backtest engine. For production
peer-symbol execution, set `GAON_REAL_MARKET_DATA_ENABLED=true` and
`GAON_MARKET_DATA_PROVIDER=yahoo-chart`; unavailable peer data remains an
explicit non-execution blocker rather than fabricated evidence.
The final Gaon v2 completion checks additionally verify the end-to-end
composition contract: Autonomous Quant Partner orchestration, Telegram
conversation context, first approval candidate freeze, second approval Champion
replacement, rollback, and the no-order/no-mutation safety boundary.
The final closeout check additionally verifies durable restart/replay recovery,
Champion replacement atomicity, rollback reason/timestamp auditability,
market-data lineage, provider readiness, Korean final-response policy, and
machine-checkable safety invariants.
The V1/V2 asset reuse audit checks additionally verify that public StrategyLab
V1 market-data, backtest, strategy, validation, memory, evidence, approval,
Champion, Telegram, persistence, and safety assets are either reused/extended
or intentionally excluded from the V2 production path. The final expected
verdict is `GAON V1/V2 INTEGRATION COMPLETE`.

Production live validation diagnostic prompt:

```text
삼성전자 전략을 처음부터 다시 연구해줘.
외부 연구 자료도 찾아보고,
지금까지 배운 내용과 실제 시장 데이터를 사용해서
문제점을 찾고 개선 전략 후보를 만든 뒤 검증해줘.
좋은 전략 후보가 생기면 승격 승인을 요청하기 전까지 진행해줘.
```

Expected Telegram diagnostics must include non-unknown `bars`, `usable_bars`,
`warmup_bars`, `entry_signals`, `completed_trades`, `minimum_required_trades`,
`sample_status`, and `horizon_extension_attempts`.

## Phase A Diagnostics

```powershell
py -3.11 -m gaon.runtime.cli config-check
py -3.11 -m gaon.runtime.cli health
py -3.11 -m gaon.runtime.cli db-check
py -3.11 -m gaon.runtime.cli status
py -3.11 -m gaon.runtime.cli metrics
py -3.11 -m gaon.runtime.cli event-replay-dry-run
```

Expected runtime DB schema version: `5`.

## Safety

Do not add:

- `.env`
- broker tokens
- account files
- private market data dumps
- production logs
- MyMoneyGuard private files

## Git Push

```bash
git push origin feature/gaon-phase-a-v2.1
```
