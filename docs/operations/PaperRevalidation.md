# Paper Revalidation Operations

Show policy:

```bash
python -m gaon.runtime.cli paper-revalidation-policy-show
```

Run revalidation:

```bash
python -m gaon.runtime.cli paper-revalidate --db runtime.sqlite --session-id paper1
```

Inspect:

```bash
python -m gaon.runtime.cli paper-revalidation-show --db runtime.sqlite <revalidation_id>
python -m gaon.runtime.cli paper-revalidation-history --db runtime.sqlite
```

`KILL` and `ROLLBACK_RECOMMENDED` are recommendations and safety records only. Rollback still requires explicit Champion Registry rollback, and live execution remains unavailable.
