# Gaon Market Context (KR_STOCK / US_STOCK / GLOBAL_STOCK / BINANCE_CRYPTO)

Status: IMPLEMENTED

Web and Telegram Gaon must explicitly distinguish which market a
conversation is about, persist it durably across turns, and never let a
different market's `ResearchMission`/candidate/conversation context be
silently continued into another market's turn.

## Resolver

`gaon.research.global_market.resolve_gaon_market_context(text)` classifies
one turn's text into exactly one of `GaonMarketContext.KR_STOCK` /
`US_STOCK` / `GLOBAL_STOCK` / `BINANCE_CRYPTO`, or `None` when the text
names no market, or names signals for more than one market at once (never
guessed - the same fail-closed contract `resolve_market_scope` already
uses for an unrecognized market).

It reuses `resolve_market_scope` in full for the KR/US/GLOBAL branches -
`KR_STOCK`/`US_STOCK` map onto that resolver's existing `"KR"`/`"US"`
scopes, and `GLOBAL_STOCK` maps onto its existing `"GLOBAL"`/`"MULTI"`
scopes (KR+US combined) - no second market-keyword engine. Binance/crypto
is the one genuinely new branch: a narrow, explicit keyword gate (바이낸스/
코인/암호화폐/가상화폐/비트코인/이더리움/binance/crypto/bitcoin/ethereum/
btcusdt/ethusdt, plus a `SYMBOLUSDT`-shaped pattern), the same style
precedent as `gaon.cognitive.presentation.binance_snapshot_reply`'s own
crypto gate. It never re-implements Binance research - `gaon.adapters.
binance` remains the sole read-only Binance state/research reader.

Company-name/ticker recognition (국내/코스피/코스닥/삼성전자 -> `KR_STOCK`;
미국/나스닥/NYSE/AAPL -> `US_STOCK`) reuses existing signals: a bare KR
6-digit code (the same pattern `extract_market_symbols` already uses for
KR), the existing `_KNOWN_KR_SYMBOL_ALIASES` company-name map from
`gaon.knowledge.research_mission` (imported lazily to avoid a module-load
cycle - the reverse lazy import already exists in that module for the
same reason), and a small, explicit well-known-US-ticker allowlist for
US_STOCK. That allowlist is deliberately NOT a generic "any bare uppercase
token" regex: this codebase's own research vocabulary is full of short
uppercase tokens that are not tickers at all - `OOS` (out-of-sample), a
single candidate label like "후보 A", `MDD`, `KPI` - and a broad regex
mis-detected `후보 A` as a US ticker during development (see
`tests/integration/test_gaon_market_context_isolation.py`'s
`test_domain_acronyms_do_not_false_positive_as_us_tickers` regression
test).

## Durable storage

`gaon.runtime.gaon_market_context.read_market_context`/
`store_market_context` persist the resolved context as a sibling key
(`gaon_market_context`) inside the SAME `conversation_sessions.
metadata_json` column `ResearchMission` already persists through (under
`conversation_mvp.research_mission`) - deliberately a sibling key, not a
new field on `ResearchMission` itself, since `ResearchMission.market` is a
KR-only field in production today (every call site sets it to the literal
string `"KR"`) and is already asserted on by existing tests/release
checks. `LLMConversationBrain.respond()` (`gaon.runtime.llm_conversation`)
writes this whenever a turn's own text names a market explicitly, before
any other routing - so a later generic follow-up ("계속 연구해줘") that
names no market of its own keeps the same stored context. Web
(`GaonWebChatAdapter`) and Telegram (`TelegramConversationAgent`) both
call this exact same `respond()`, so both transports share one policy by
construction (see `docs/architecture/GaonBinanceConversationDashboardIntegration.md`).

## Cross-market isolation (fail-closed)

`gaon.knowledge.research_mission.is_mission_market_compatible(mission,
text, market_context=...)` is the narrow, market-only compatibility check:
a mission is compatible only when the turn's EFFECTIVE market context
(explicit-in-text, else the durable stored context) matches the mission's
own market, or when no context is known either way. It is deliberately
separate from `is_mission_compatible_with_request` (which also checks
strategy-family compatibility) so that pivoting strategy family WITHIN an
established mission - feature/conversation-paradigm-family-routing (A9) -
is unaffected.

Two call sites enforce this:

- **Same session**: `LLMConversationBrain._try_conversational_mvp` nulls
  out the session-local mission for the CURRENT turn (never mutates or
  deletes the persisted mission itself) whenever it is market-incompatible
  with the turn's effective context - e.g. a KR mission already active in
  a chat is set aside (not continued/extended) for a later "바이낸스 코인
  전략 계속 연구해줘" turn in the SAME chat.
- **Cross-transport/cross-session**: `_resolve_durable_owner_mission`
  passes the effective market context into
  `is_mission_compatible_with_request`, so the durable owner-scoped
  lookup (Telegram <-> Web, when `GAON_OWNER_REF`/allowlists are
  configured) never hands back a mission from a different market context
  either.

## What is deliberately NOT added

No new BINANCE_CRYPTO/US_STOCK/GLOBAL_STOCK "ask which market" clarification
prompt intercepts a bare continuation phrase with no context anywhere. An
earlier version of this change added one and it collided with this
codebase's own extensive, already-battle-tested "no context -> ask
honestly, never guess" architecture across many prior hotfixes
(152.1/163.1-5/185.1-5/etc - see `README.md`'s Release Candidate Status
list) - see `tests/integration/test_telegram_conversation_agent.py`'s
`test_hotfix1851_autonomous_learning_missing_context_asks_target` and
`test_hotfix1633_progression_context_is_chat_isolated`, which assert the
EXISTING honest fallback text for exactly that scenario. The fail-closed
guarantee this change adds is instead: (1) the resolver itself never
guesses across markets (returns `None` for a mixed signal, and never
overwrites an already-stored context with a guess), and (2) an existing
mission is never silently treated as compatible with a different market's
turn (above). Both are covered by
`tests/integration/test_gaon_market_context_isolation.py`.

## Safety

Read-only classification and context storage only. No live trading,
KIS/Broker order, automatic Champion promotion, approval bypass, strategy
mutation, service restart, or production deployment is added.
