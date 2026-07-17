# Backup and Restore

Status: Sprint 21 runtime state guide

Runtime SQLite stores operational state only. It must not store secrets.

## Backup

- stop writes or use SQLite backup API
- run `python -m gaon.runtime.cli backup --db <runtime.sqlite> --destination <backup.sqlite>`
- record checksum
- keep Learning Memory JSON export separate

## Restore

1. Run restore dry-run.
2. Validate schema version.
3. Confirm overwrite explicitly.
4. Restore SQLite backup.
5. Run `python -m gaon.runtime.cli db-check --db <path>`.

Notion is a secondary copy only, not the source of truth.
