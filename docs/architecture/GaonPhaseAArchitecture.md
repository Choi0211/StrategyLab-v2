# Gaon Phase A Architecture

Status: v2.1 Release Candidate

Gaon Phase A adds platform foundations around the existing StrategyLab runtime:

- assistant provider registry and deterministic routing
- explicit plugin lifecycle management
- internal metrics and observability
- durable event store and safe replay
- long-term memory foundation
- runtime construction order and graceful shutdown

## Construction Order

1. Load runtime configuration.
2. Open SQLite runtime state and run forward-only migrations.
3. Build metrics collector.
4. Build provider registry and selected assistant provider.
5. Build plugin registry and plugin manager.
6. Build durable event store.
7. Build long-term memory repository.
8. Start runtime service, then plugin manager.
9. Run controlled loop.
10. Stop runtime service and plugins in reverse dependency order.

## Safety Boundaries

Phase A is not production trading ready. It performs no live Telegram, OpenAI, Notion, broker, KIS, VPS, or MyMoneyGuard validation.

All external capabilities remain disabled by default or fake/deterministic in tests.
