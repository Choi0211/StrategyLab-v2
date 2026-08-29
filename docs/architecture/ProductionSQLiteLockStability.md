# Production SQLite Lock Stability Hotfix

Status: Implemented (backend only). Scope is deliberately narrow: telemetry
failure isolation, explicit bounded busy timeout, and migration ownership.
**No journal-mode change** (see WAL Decision below).

## Incident

Production (`/var/lib/strategylab/gaon-runtime.sqlite`, shared by
`strategylab-gaon` and `gaon-web`): `strategylab-gaon` repeatedly crashed
(`NRestarts>=6`) with `sqlite3.OperationalError: database is locked`, in
two distinct places:

1. `TelegramPollingWorker._append_event(...)` (a non-critical,
   purely-operational telemetry write - `TelegramPollingTickCompleted`/
   `TelegramPollingTickFailed`) raised an uncaught lock error that
   propagated all the way through `GaonRuntimeService.run_forever()` and
   killed the process.
2. `RuntimeStateStore.__init__` -> `migrate()` hit the same error during
   startup, because both `strategylab-gaon` and `gaon-web` independently
   and unconditionally called `migrate()` on the same file with no
   coordination.
3. The lock also recurred at a time unconnected to any deployment
   (03:33:39), confirming this is not deployment-only - it is ongoing
   two-process write contention under SQLite's default rollback-journal
   (`journal_mode=delete`) locking model, where every write briefly takes
   an exclusive lock on the whole file.

## Root Cause

Not a long-held transaction (verified: every write in this codebase is a
short, single-statement transaction) and not literally `busy_timeout=0` at
the application level (Python's `sqlite3.connect()` already defaulted to a
5-second timeout, which neither connection overrode downward - the
production `busy_timeout=0` observed via the `sqlite3` CLI reflects that
CLI session's own fresh connection, not the live application connections).
The real causes: (a) an unguarded, unserialized second migration attempt
racing the first at startup, and (b) two independent long-running
processes sharing one rollback-journal-mode file with no coordination,
combined with (c) zero exception handling around exactly one non-critical
write, turning an ordinary (if previously un-hardened) SQLite retry
situation into a full process crash.

## Telemetry vs Critical State Distinction

This hotfix isolates lock/busy failures **only** for
`TelegramPollingWorker._append_event` - the exact two event types
(`TelegramPollingTickCompleted`, `TelegramPollingTickFailed`) confirmed to
be pure operational telemetry: by the time either is appended, the tick's
real work (`poll_once` - real Telegram message processing, any replies
already sent) has already completed and separately committed. Losing one
has zero correctness impact.

`gaon.runtime.event_store.SQLiteEventStore.append()` **itself is
completely unchanged** - it is used by Champion registry, trading
execution, scheduler, and daily-research event writes elsewhere in this
codebase, all of which remain exactly as strict as before this hotfix. The
isolation lives entirely inside `TelegramPollingWorker._append_event`,
scoped to that one caller.

**What is isolated**: only `sqlite3.OperationalError` classified by
`gaon.runtime.sqlite_lock.is_lock_or_busy_error` as genuine lock/busy
contention (`"database is locked"` / `"database is busy"` in the error
message). Every other case still propagates uncaught, exactly as before:

- a different `OperationalError` (corrupted database, missing table,
  schema error, disk I/O error, ...) - never caught;
- any non-SQLite exception (a programming error) - never caught;
- a dropped telemetry event is never silent - it increments
  `telegram_telemetry_append_dropped` and logs a structured warning, and
  the dropped write is never retried by writing another event about the
  drop (no recursive-failure DB write).

## Explicit Bounded SQLite Timeout

`gaon.runtime.sqlite_lock.DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS = 5.0` - the
**same value** Python's `sqlite3` module already applied implicitly (its
own default `timeout=5.0` when none is passed) and the same value
`gaon-web`'s per-request connection already passed explicitly before this
hotfix. This hotfix does not invent a new number; it makes the existing,
already-relied-upon behavior explicit, tested, and shared from one place
(both `RuntimeStateStore` and `gaon-web`'s `scoped_adapter` now set
`timeout=` and `PRAGMA busy_timeout` from this one constant).

`gaon.runtime.sqlite_lock.retry_on_lock(fn, attempts=3, base_delay_seconds=0.2)`
wraps `migrate()` for the migration owner: retries ONLY on a classified
lock/busy error, with a small linear backoff, bounded by `attempts` (never
infinite), and re-raises the last lock error (fail-closed) if contention
never clears within the budget. Safe to retry the entire `migrate()` call
from the top because every migration step is idempotent DDL (`CREATE
TABLE/INDEX IF NOT EXISTS`).

## Migration Ownership

`strategylab-gaon` (the `run`/`status`/`health`/`readiness`/`db-check` CLI
commands) remains the schema migration **owner** -
`RuntimeStateStore(path)` (default `owns_migration=True`) behaves exactly
as before, now wrapped in the bounded retry above.

`gaon-web-serve` is now a migration **non-owner** -
`RuntimeStateStore(path, owns_migration=False)` never writes to the
schema. It performs exactly one read-only `SELECT` via
`gaon.runtime.migrations.check_schema_version_compatible` and **fails
closed** (`gaon.runtime.errors.SchemaVersionMismatchError`, a
`GaonRuntimeError` - caught by the CLI's existing `except GaonRuntimeError`
handler, printed as a clean error, process exits 1) if the schema is
missing (never migrated), older, or newer than what this build expects.
`gaon-web` can therefore never race the owner's migration with a
concurrent write, and can never silently start against a stale or
in-progress schema.

## Schema Version Source of Truth

Unchanged: the application-level `schema_version` table (read via `SELECT
version FROM schema_version ORDER BY version DESC LIMIT 1`), **not**
SQLite's `PRAGMA user_version`. This hotfix does not introduce
`PRAGMA user_version` or any second source of truth - schema stays at
**v39** (no migration was needed for this hotfix).

## WAL Decision

**Deliberately deferred.** `journal_mode` is not changed by this hotfix -
`PRAGMA journal_mode=WAL` is not executed anywhere, and the release check
asserts `wal_enabled=false`. WAL is a plausible structural improvement
(concurrent readers alongside one writer, reduced exclusive-lock
frequency) but changes the on-disk format to three files
(`.sqlite`/`.sqlite-wal`/`.sqlite-shm`), and this repository's backup/
archive/lifecycle tooling (`deploy/scripts/storage_lifecycle_manager.py`)
has not yet been audited for compatibility with that format - a plain
file copy while WAL is active can produce an inconsistent backup. **WAL
deferred pending operational compatibility audit** covering backup,
archive, lifecycle, disk-to-disk sync, DB copy/restore, and crash
recovery - a separate, future investigation/PR, not bundled here.

## Safe Deployment Procedure

Until migration ownership is fully proven safe under real production
timing (this hotfix removes the *code-level* race for `gaon-web`, but a
transitional window still exists during a rolling deploy where an
old-code `gaon-web` process, not yet restarted, could still attempt its
own migration against a `strategylab-gaon` that is simultaneously
migrating), the recommended procedure for any deploy that changes
`SCHEMA_VERSION` is:

1. `systemctl stop strategylab-gaon`
2. `systemctl stop gaon-web`
3. Backup the database and confirm `PRAGMA quick_check = ok`.
4. Migrate once, explicitly, using the migration owner's path - e.g.
   `python -m gaon.runtime.cli db-check --db /var/lib/strategylab/gaon-runtime.sqlite`
   (constructs `RuntimeStateStore` with the default `owns_migration=True`,
   applies any pending migration, then exits) rather than starting the
   long-running `run` service for this step.
5. Verify the reported `schema_version` matches the new build's
   `SCHEMA_VERSION`.
6. `systemctl start strategylab-gaon`
7. `systemctl start gaon-web`
8. Verify health (`db-check`/`health` CLI, and `gaon-web`'s own health
   endpoint) on both services.

For a deploy that does **not** change `SCHEMA_VERSION`, this strict
stop-migrate-start sequence is not required - the code-level fixes in this
hotfix (bounded retry, non-owner fail-closed check) are the standing
protection for ordinary restarts. This procedure exists specifically to
eliminate the two-process concurrent-migration window during a genuine
schema bump, and should be treated as the standing rule for future schema
migrations, not an ad hoc workaround remembered only after an incident.

## Known Limitations

- This hotfix does not eliminate all possible lock contention - it makes
  the timeout explicit and bounded, isolates one specific non-critical
  failure, and removes the migration race. Genuine, ongoing two-process
  write contention under `journal_mode=delete` is a structural
  characteristic of this architecture until WAL (or a single-writer
  redesign) is adopted - deferred, per above.
- The transitional rolling-deploy window described in Safe Deployment
  Procedure (an old-code `gaon-web` still running during a schema bump)
  is mitigated by the stop-migrate-start procedure, not eliminated at the
  code level, since it depends on which code version is running, not
  which code version is being deployed.
- `RuntimeStateStore.backup()`'s own internal temporary-file connections
  are unchanged by this hotfix (they operate on an exclusive temp file
  during the backup operation itself, not the shared production file, so
  they were not in scope for this incident).
