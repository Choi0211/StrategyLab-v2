# Strategy Handoff Operations

Create a package from an active Champion and LIVE_ELIGIBLE paper revalidation:

```bash
python -m gaon.runtime.cli handoff-create --db runtime.sqlite --champion-slot default --revalidation-id rv-live
```

Inspect and export:

```bash
python -m gaon.runtime.cli handoff-show --db runtime.sqlite <package_id>
python -m gaon.runtime.cli handoff-export --db runtime.sqlite --package-id <package_id> --output ./strategy-package.json
```

Approve or reject:

```bash
python -m gaon.runtime.cli handoff-approve --db runtime.sqlite <package_id>
python -m gaon.runtime.cli handoff-reject --db runtime.sqlite <package_id> --reason "not ready"
```

Explicit `handoff-approve` is required before any future deployment workflow can
consume the package.
