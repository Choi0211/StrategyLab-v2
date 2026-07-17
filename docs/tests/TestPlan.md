# StrategyLab v2 Test Plan

Status: Sprint 12 Runtime

## Unit Tests

Sprint 1 requires:

- import smoke tests
- example config loader tests
- logger initialization tests
- module registry tests
- plugin loader discovery tests

Sprint 1 uses the Python standard library test runner so the foundation can be verified without external dependencies:

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit
```

Sprint 2 adds:

- market model construction tests
- provenance construction tests
- validation pass for valid fixture
- validation failure for missing values
- validation failure for duplicate timestamps
- validation failure for empty dataset
- validation failure for symbol mismatch
- validation failure for date range mismatch
- validation failure for invalid OHLC
- validation failure for negative volume
- in-memory adapter retrieval tests
- in-memory adapter date filtering tests

Sprint 3 adds:

- strategy parameter default tests
- strategy parameter type validation tests
- strategy parameter bounds validation tests
- strategy config round-trip tests
- strategy registry registration tests
- strategy registry duplicate rejection tests
- deterministic signal generation tests
- signal output contract tests

Sprint 4 adds:

- backtest config construction tests
- trade record construction tests
- equity curve record construction tests
- known-scenario runner tests
- deterministic result ID tests
- deterministic trade log tests
- deterministic equity curve tests
- transaction cost tests
- slippage tests

Sprint 5 adds:

- cash ledger debit/credit tests
- position buy/sell/value tests
- portfolio snapshot tests
- allocation target validation tests
- rebalance instruction tests
- fixed quantity sizing tests

Sprint 6 adds:

- max drawdown tests
- exposure tests
- risk score tests
- emergency stop tests
- circuit breaker tests
- ATR position sizing tests

Sprint 7 adds:

- deterministic AI review prompt tests
- AI review result schema validation tests
- fallback review tests

Sprint 8 adds:

- dashboard summary assembly tests
- metric card and table view contract tests

Sprint 9 adds:

- broker order/fill contract tests
- paper broker fill tests
- paper broker rejection tests

Sprint 10 adds:

- release artifact existence tests
- release verification script
- end-to-end integration test
- GitHub Actions verification on Ubuntu and Windows with Python 3.11 and 3.12

Sprint 11 adds:

- Gaon package import smoke test
- Learning Memory evidence requirement tests
- required Learning Memory category tests
- Knowledge lifecycle transition tests
- user approval requirement for `Validated` knowledge
- policy update evidence and rollback tests
- forbidden autonomous action contract tests
- Research Brain import smoke test
- Research Goal evidence and Learning Memory export tests
- Research Plan deterministic construction tests
- Research Session goal/plan matching tests
- Research Session invalid transition tests
- Research Session completed-state terminal tests
- Research Interview question/answer alignment tests
- Research Interview pending question tests
- Research Journal immutability and duplicate rejection tests
- Research Brain versioned JSON round-trip tests

Sprint 12-A adds:

- Learning Memory contract import tests
- evidence-required tests for new domain contracts
- immutable dataclass behavior tests
- KnowledgeApproval gate tests
- PolicyApproval and rollback gate tests
- ConfidenceScore cannot approve tests
- UserPreference automatic overwrite/delete prevention tests
- versioned JSON round-trip tests
- invalid kind and unsupported version rejection tests
- no secret/private/live trading import tests

Sprint 12 runtime adds:

- duplicate ID rejection
- evidence-less repository import rejection
- immutable repository copy protection
- deep immutable metrics protection
- chronological UTC ordering and timestamp tie-breaks
- scope/project/strategy/market/record type filters
- duplicate candidate detection without merge
- conflict candidate detection without resolution
- approval scope mismatch rejection
- PreferenceApproval type separation
- invalid UTC and non-UTC timestamp rejection
- audit append-only behavior
- duplicate audit ID rejection
- audit target/action query
- related-memory deterministic ranking
- retrieval score breakdown
- conflict and revalidation penalties
- repository JSON round-trip
- v0 to v1 migration
- unsupported version and malformed fixture rejection
- Research Brain conversion and no-auto-save workflow
- no DB/vector/external AI/private/live trading imports

Gaon Runtime Collaboration adds:

- configuration secret masking and fail-closed validation
- deterministic event bus subscriber order and failure isolation
- Conversation Runtime command and Korean natural-language intent parsing
- approval safety responses without approval mutation
- Telegram update parsing, allowed chat authorization, Markdown escaping, long message splitting, dry-run response
- Telegram Bot API client `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook`, and `getWebhookInfo` contract tests with fake HTTP
- Telegram HTTP 401/429/500, malformed JSON, `ok=false`, timeout, token masking, discover-chat deduplication, and offset handling tests
- Telegram production smoke CLI gate tests for `telegram-get-me`, `telegram-discover-chat`, `telegram-send-smoke`, and `telegram-poll-once`
- Notion research/memory/report mapping and dry-run idempotency
- NotificationRequest/NotificationResult mapping and deduplication
- deterministic DailyReport and WeeklyReview
- in-memory Scheduler due job and duplicate run prevention
- CLI dry-run command routing
- Learning Memory claims snapshot export/import
- STRICT/BROAD/GLOBAL related-memory retrieval modes
- token overlap, alias matching, and EvidenceType quality scoring
- no real network call, no shell execution, no broker/trading import

## Integration Tests

Sprint 12 runtime adds an end-to-end Learning Memory integration:

ResearchGoal -> ResearchPlan -> completed ResearchSession -> ResearchOutcome -> duplicate/conflict preparation -> Repository add -> AuditEvent append -> Related Memory retrieval -> JSON export -> Repository import -> same retrieval result.

Telegram production smoke connection adds fake-transport integration flows:

- getUpdates -> discover unique private chat
- allowed `/status` update -> Conversation Runtime -> sendMessage
- unauthorized update -> no sendMessage
- long response chunks -> same chat delivery

## Research Validation

Research validation in Sprint 4 is limited to a known-scenario deterministic fixture. No production research validation is required yet.

## Secret Check

Every sprint must verify that forbidden secret-bearing files are not tracked.
