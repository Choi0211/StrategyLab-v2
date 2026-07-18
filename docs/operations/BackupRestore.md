# Backup and Restore

Status: Sprint 22 runtime state guide

Runtime SQLite stores operational state only. It must not store secrets.

## Backup

- use the runtime SQLite backup API
- run `python -m gaon.runtime.cli backup --db <runtime.sqlite> --destination <backup.sqlite>`
- backup writes to a temporary destination and atomically replaces the final file
- restored backups must pass `db-check`
- record checksum
- keep Learning Memory JSON export separate

## Restore

1. Run restore dry-run.
2. Validate schema version.
3. Confirm overwrite explicitly.
4. Restore SQLite backup.
5. Run `python -m gaon.runtime.cli db-check --db <path>`.

Notion is a secondary copy only, not the source of truth.

## v5 Deployment Recovery

- Stop the service before replacing a runtime DB.
- Never overwrite the user's runtime DB from a script without an explicit operator action.
- Keep deployment backups separate from runtime DB backups.
- If deployment verification fails after apply, use the recorded deployment backup and rollback result.
- After restore or rollback, run:
  - `python -m gaon.runtime.cli db-check --db <runtime.sqlite>`
  - `python -m gaon.runtime.cli health --db <runtime.sqlite>`
  - `python -m gaon.runtime.cli deployment-history --db <runtime.sqlite>`
