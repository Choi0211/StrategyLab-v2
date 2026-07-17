# ADR-0011: Durable Event Store and Replay

Status: Accepted

Runtime events are persisted in an append-only SQLite event store.

Replay is deterministic, bounded, and dry-run by default. Checkpoints advance only after successful non-dry-run projection processing.

Consequences:

- duplicate event IDs are rejected
- malformed and oversized payloads fail closed
- projection failures are isolated and recorded
- side effects are suppressed during diagnostics
