# Champion / Challenger Evaluation Operations

Status: Sprint 43

Use this after both backtest results exist and the Challenger has a persisted Sprint 42 `ValidationReport`.

## CLI

```powershell
py -3.11 -m gaon.runtime.cli champion-policy-show
py -3.11 -m gaon.runtime.cli champion-evaluate --db runtime.sqlite --champion-backtest-id <id> --challenger-backtest-id <id> --validation-id <id>
py -3.11 -m gaon.runtime.cli champion-evaluation-show --db runtime.sqlite <evaluation_id>
py -3.11 -m gaon.runtime.cli champion-evaluation-history --db runtime.sqlite
```

The evaluation command requires an explicit Challenger validation id. It cannot bypass Sprint 42 validation.

## Decisions

- `promotion_candidate`: the Challenger is eligible for future human review as a promotion candidate.
- `keep_champion`: the Champion remains selected by policy.
- `review`: the comparison is incomplete or ambiguous and needs human review.

`promotion_candidate` does not change any active strategy and does not deploy or trade.

## Safety

No live KIS, broker credentials, real orders, automatic trading, automatic approval, MyMoneyGuard dependency, arbitrary shell execution, or paid-provider fallback is required or connected.
