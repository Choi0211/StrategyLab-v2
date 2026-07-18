# Champion Registry Operations

Sprint 44 provides approval-based Champion registration and promotion.

## Bootstrap

Bootstrap is explicit and administrative. It does not auto-select from historical backtests.

```bash
python -m gaon.runtime.cli champion-bootstrap --db runtime.sqlite --strategy turtle_v5 --fingerprint <fingerprint> --backtest-id <backtest_id>
```

## Promotion

Create a request from a Sprint 43 `promotion_candidate` evaluation:

```bash
python -m gaon.runtime.cli champion-promotion-request --db runtime.sqlite --evaluation-id <evaluation_id>
```

Approve explicitly:

```bash
python -m gaon.runtime.cli champion-promotion-approve --db runtime.sqlite <promotion_id>
```

Reject explicitly:

```bash
python -m gaon.runtime.cli champion-promotion-reject --db runtime.sqlite <promotion_id>
```

## Inspect

```bash
python -m gaon.runtime.cli champion-registry-show --db runtime.sqlite
python -m gaon.runtime.cli champion-history --db runtime.sqlite
```

## Rollback

Rollback restores the immediate previous Champion by creating a new history version.

```bash
python -m gaon.runtime.cli champion-rollback --db runtime.sqlite
```

## Boundaries

These commands update only the StrategyLab Champion registry and history. They do not place orders, switch live strategies, connect to KIS, or access MyMoneyGuard.
