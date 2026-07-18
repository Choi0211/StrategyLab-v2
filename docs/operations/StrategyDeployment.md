# Strategy Deployment Operations

Plan deployment for an approved handoff package:

```bash
python -m gaon.runtime.cli deployment-plan --db runtime.sqlite --package-id <package_id>
```

Run the plan with the default fake adapter:

```bash
python -m gaon.runtime.cli deployment-run --db runtime.sqlite --plan-id <plan_id>
```

Run against a bounded local-safe target directory:

```bash
python -m gaon.runtime.cli deployment-run --db runtime.sqlite --plan-id <plan_id> --target-dir ./local-safe-target
```

Inspect:

```bash
python -m gaon.runtime.cli deployment-status --db runtime.sqlite
python -m gaon.runtime.cli deployment-history --db runtime.sqlite
python -m gaon.runtime.cli deployment-backups --db runtime.sqlite
```

No private repository, broker credentials, or live trading adapter is required
or used by the public workflow.
