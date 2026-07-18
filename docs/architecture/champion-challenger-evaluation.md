# Champion / Challenger Evaluation Engine

Status: Sprint 43

The Champion / Challenger Evaluation Engine compares an existing Champion backtest result against a Challenger backtest result that has already passed through Sprint 42 validation.

`PROMOTION_CANDIDATE` is not `PROMOTED`.

## Flow

```text
BacktestResult
-> Validation Engine
-> PASS / FAIL / REVIEW
-> Champion / Challenger Evaluation
-> KEEP_CHAMPION / PROMOTION_CANDIDATE / REVIEW
-> EvaluationReport
-> Human Review / Future Promotion Pipeline
```

Sprint 43 creates evaluation reports only. It does not change the active strategy and does not connect evaluation output to trading.

## Domain Contracts

- `StrategyRole`
- `ChampionChallengerDecision`
- `ChampionChallengerEvaluationRequest`
- `ChampionChallengerPolicy`
- `ChampionChallengerMetricComparison`
- `ChampionChallengerEvaluationReport`

Decisions:

- `KEEP_CHAMPION`
- `PROMOTION_CANDIDATE`
- `REVIEW`

## Policy v1

`champion_challenger_policy_v1` uses deterministic gates:

- Challenger validation must be `PASS`.
- Champion and Challenger fingerprints must both exist.
- Fingerprints must be different.
- Challenger total return must improve by at least 5 percentage points.
- Challenger MDD must not be more than 5 percentage points worse than Champion MDD.
- If both profit factors exist, Challenger profit factor must be at least Champion profit factor.
- Missing optional metrics are not fabricated.
- Sample period and trade count are recorded for explainability; major sample comparability concerns can trigger review.

MDD uses the Sprint 42 positive-fraction convention through the same normalization helper.

## Decision Semantics

`PROMOTION_CANDIDATE` requires all hard gates and comparison gates to pass.

`KEEP_CHAMPION` is returned when the Challenger validation fails, return improvement is insufficient, risk degradation exceeds policy, Challenger is clearly inferior, or fingerprints are identical.

`REVIEW` is returned when Challenger validation is `REVIEW`, required comparison data is missing, optional metrics are not evaluated, or metadata comparability is ambiguous.

## Explainability

Every report includes rule-level comparisons:

- metric name
- Champion value
- Challenger value
- difference
- threshold
- status
- explanation

The `evaluation_score` is explanatory only. It cannot override a hard gate.

## Persistence, Events, Metrics

Runtime schema v14 adds:

- `champion_challenger_evaluation_requests`
- `champion_challenger_evaluation_reports`

Events:

- `ChampionChallengerEvaluationRequested`
- `ChampionChallengerEvaluationCompleted`
- `PromotionCandidateIdentified`
- `ChampionRetained`
- `ChampionChallengerReviewRequired`

Metrics:

- `champion_challenger_evaluations_total`
- `promotion_candidates_total`
- `champion_retained_total`
- `champion_challenger_reviews_total`

## Safety Boundary

The engine does not implement automatic Champion promotion, active strategy switching, live KIS, broker credentials, real orders, automatic trading, automatic approval, MyMoneyGuard dependency, arbitrary shell execution, or paid-provider fallback.

There is no code path from `PROMOTION_CANDIDATE` to `TradingExecutionService` or active strategy mutation.
