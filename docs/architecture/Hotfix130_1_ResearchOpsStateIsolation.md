# Hotfix 130.1 Research Operations State Isolation

## Problem

`research-ops-release-check` and `research-ops-demo` created fixture reports,
approvals, strategy configuration versions, and audit rows in the same SQLite
database used by production runtime. The read-only `research_operation_status`
tool then reported those release-check challenger/config rows as if they were
real operational research state.

## Isolation Design

Research Operations data is classified by provenance-bearing identifiers.
Artifact prefixes are reserved for non-production data:

- `research-ops-release-check:`
- `research-recommendation:research-ops-release-check:`
- `research-ops-demo:`
- `research-recommendation:research-ops-demo:`
- `test:`
- `unit:`
- `integration:`

Production status queries exclude those artifacts by default. Real user
research reports and approved strategy configuration versions remain visible.

`research-ops-release-check` validates the target database schema, then executes
fixture writes in an isolated in-memory runtime store. It verifies that the
target production research operation tables are unchanged after the check.

`research-ops-demo` also uses an isolated store by default. A deliberate
`--persist` flag can create demo artifacts for local diagnostics, but those
artifacts remain hidden from normal status output and are cleanup eligible.

## Cleanup Design

`research-ops-cleanup` supports:

- `--dry-run`: report matching release-check/demo/test artifacts without changing
  the database.
- `--apply`: delete only identified artifacts and append a cleanup audit row.

Cleanup targets only rows whose identifiers or payload provenance match the
reserved artifact prefixes. It does not delete real user research reports,
approvals, or configuration versions.

## Safety

This hotfix does not add trading, broker access, KIS access, Champion auto
promotion, Telegram write mutation, or approval bypass. Strategy configuration
changes still require explicit human approval.
