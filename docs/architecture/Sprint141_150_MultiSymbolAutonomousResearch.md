# Sprint 141-150 Multi-Symbol Autonomous Research

## Blueprint

Sprint 141-150 extends Gaon from single-symbol real research into bounded
multi-symbol KRX research. The system applies one user-provided strategy and
one execution-assumption set to an explicit or curated KRX universe, then
records per-symbol evidence, cross-symbol aggregation, robustness,
concentration, sample sufficiency, candidate generalization, and a
deterministic Korean report.

The sprint remains research-only. It does not add live trading, KIS/broker
orders, automatic Champion promotion, approval bypass, or strategy config
mutation.

## Data Model

Core contracts:

- `MultiSymbolResearchRequest`
- `MultiSymbolResearchRun`
- `SymbolResearchEvidence`
- `CandidateSymbolEvidence`
- `UniverseResearchSummary`
- `CandidateGeneralization`
- `KRXResearchUniverse`

Every run records:

- `run_id`
- `universe_id`
- `symbols`
- `strategy_fingerprint`
- `assumptions_fingerprint`
- `period`
- `provider`
- `source`
- `fixture_backed`
- `created_at`

## Universe Provenance

Supported universe types:

- `explicit`: user-provided or explicitly supplied symbol list.
- `curated`: deterministic static KRX research universe.

The initial production verification universe is explicit:

- `005930`
- `000660`
- `005380`
- `035420`
- `051910`

This sprint does not claim a live top-volume or historical dynamic universe.
When a current explicit list is used over historical periods, reports must
preserve survivorship-bias awareness through explicit provenance rather than
pretending the universe was known historically.

## Data Quality

Each symbol is fetched and validated independently through the existing KRX
real-market data path:

- historical KRX calendar
- provider gap policy
- provider OHLC anomaly policy
- provider zero-volume anomaly policy
- symbol-specific anomaly isolation
- fail-closed unknown/malformed data handling

A blocking symbol does not automatically fail the whole run. It becomes
ineligible, and the final run evaluates whether remaining universe coverage is
sufficient.

## Cross-Symbol Aggregation

Aggregation is independent-symbol evidence aggregation, not a portfolio
backtest. The engine records:

- total symbols
- eligible symbols
- blocked symbols
- symbols with trades
- aggregate trade count
- median return
- median MDD
- positive-return symbol ratio
- profitable symbol ratio
- trade concentration
- return concentration
- best symbol
- worst symbol

## Robustness

Concentration decisions are deterministic:

- `broad`
- `moderately_concentrated`
- `highly_concentrated`
- `insufficient_evidence`

If most evidence comes from one symbol, the strategy is not labeled a
generalized edge.

## Sample Sufficiency

Sample confidence uses:

- aggregate trade count
- minimum symbols with trades
- eligible universe coverage
- concentration
- single-symbol dependence

Confidence values:

- `low`
- `medium`
- `high`

Trade count alone is not enough to claim sufficient evidence.

## Candidate Generalization

Original and TESTED candidates are applied across eligible symbols with the
same strategy and assumption fingerprint discipline. Candidate decisions are:

- `original_preferred`
- `candidate_preferred`
- `no_clear_winner`
- `needs_more_evidence`

No Champion promotion is performed.

## Telegram Flow

Explicit multi-symbol requests take the authoritative path:

`Telegram -> LLMConversationBrain -> multi_symbol_research -> deterministic Korean report`

The route is read-only and provider-free for authoritative execution.
LLM-generated numbers are not required for the final report.

## Persistence

Schema v36 adds:

- `multi_symbol_research_runs`
- `multi_symbol_symbol_evidence`
- `multi_symbol_candidate_evidence`
- `multi_symbol_universe_snapshots`

Release-check, demo, unit, and integration artifacts are hidden from normal
status/history views unless explicitly included by repository internals.

## Safety

Preserved boundaries:

- No live trading
- No KIS/broker order
- No automatic Champion promotion
- No approval bypass
- No automatic config mutation
- No Telegram mutation
- No arbitrary shell/SQL
- No private repository dependency

## Known Limitations

- Dynamic KRX top-volume universe selection is not implemented.
- The default production verification universe is the explicit five-symbol set.
- Multi-symbol aggregation is not a portfolio simulation.
- Release checks use a synthetic real provider to avoid network dependency in CI.

## Production Verification

```bash
python -m gaon.runtime.cli multi-symbol-research-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Real Yahoo KRX verification on VPS:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli multi-symbol-research-demo \
  --db /var/lib/strategylab/gaon-runtime.sqlite \
  --persist \
  --symbols 005930,000660,005380,035420,051910
```

Inspect persisted state:

```bash
python -m gaon.runtime.cli multi-symbol-research-status --db /var/lib/strategylab/gaon-runtime.sqlite
python -m gaon.runtime.cli multi-symbol-research-history --db /var/lib/strategylab/gaon-runtime.sqlite
```
