# Strategy Execution Runtime Operations

Show policy:

```bash
python -m gaon.runtime.cli execution-policy-show
```

Inspect state:

```bash
python -m gaon.runtime.cli execution-status --db runtime.sqlite
python -m gaon.runtime.cli execution-history --db runtime.sqlite
```

Plan and run paper execution:

```bash
python -m gaon.runtime.cli execution-plan --db runtime.sqlite --mode paper
python -m gaon.runtime.cli execution-run --db runtime.sqlite --plan-id <plan_id>
```

Plan live execution:

```bash
python -m gaon.runtime.cli execution-plan --db runtime.sqlite --mode live --revalidation-id <revalidation_id>
```

Live execution is intentionally blocked in Sprint 47 with `live broker adapter unavailable`.

Environment defaults:

```bash
GAON_EXECUTION_MODE=disabled
GAON_LIVE_TRADING_ENABLED=false
```

Do not set live trading variables expecting real execution. Sprint 47 has no live broker adapter.
