# Gaon Cognitive Core v1 + Unified Conversation Experience

Status: LOCAL IMPLEMENTATION VERIFIED; overall scope remains PARTIAL as declared below.

## Authority and baseline

StrategyLab-v2 main bcdb0a0 owns cognition, durable conversation, research and
rendering. binance_ai_bot master 596130d owns browser identity, proxy and UI.
No research implementation is copied into the dashboard. Existing uncommitted
cognitive models/repository/orchestrator are continued, not discarded.

## Existing modules

- LLMConversationBrain.respond: shared Telegram/Web entry, existing safety gates.
- ConversationContextOrchestrator: recent history and bounded runtime retrieval.
- SQLiteLongTermMemoryRepository: durable preference/proposed knowledge reuse.
- ResearchMission and existing Research Brain: only research execution authority.
- AgentPlanner/SafeToolExecutor: only existing approved execution authority.
- RuntimeStateStore/migrations: additive durable state and backup support.
- web_api.GaonWebChatAdapter: Web session and response contract.
- dashboard.chat/_ask_gaon: remove unconditional JSON prompt injection.

## Contracts

Raw user text is separate from context. Browser IDs are continuity identifiers,
not authentication. Anonymous user memory is browser-scoped; authenticated
cross-device identity requires a future authenticated principal mapping.
No client-supplied identity authorizes orders or configuration changes.
Feedback is a user preference, not verified market knowledge. Acquired material
is data; no code execution or automatic trusted knowledge promotion.
Goals/reflective proposals do not independently execute tools. Research delegates
to the existing brain and retains all evidence/approval gates.

## Persistence

Add schema v37 cognitive_records with a namespace index; preserve all v36 tables.
Reuse long_term_memory for preference and learning proposals. Cognitive records
hold goals, reflections, gaps, project/tool metadata and operational self model.
Migration must be idempotent; production DB is not accessed during development.

## Delivery stages

0 mapping/blueprint; 1 models/persistence; 2 feedback/retrieval; 3 goals/reflection;
4 learning/gaps; 5 planning/proactive/project/tools; 6 existing research integration;
7 Web contract; 8 browser identity/proxy; 9 independent mobile Gaon view;
10 regression/release/render verification. Report IMPLEMENTED/PARTIAL/FOUNDATION
ONLY/BLOCKED/DEFERRED per capability, never equate a data model with execution.

## Verification and rollback

Use isolated SQLite and fake network clients. Test restart, namespace isolation,
retrieval budget, greeting isolation, feedback application, evidence gates and
unchanged research regressions. Verify mobile 360x800, 390x844, 412x915.
No orders, services, deployments, push or PR. Older v36 binaries reject schema
v37. A later authorized rollback requires a pre-migration backup and recovery of
any subsequent writes. Never edit the schema version or delete existing data.

## Implementation boundaries

| Feature | Before | After | Status |
| --- | --- | --- | --- |
| General greeting | stale context/provider path possible | deterministic shared-brain greeting, no research tools | IMPLEMENTED |
| Unrelated conversation | global research snapshots included | query-filtered context, recent conversation retained | IMPLEMENTED |
| User feedback | history only | scoped durable preference used by status renderer | IMPLEMENTED |
| Goal | research-only state | persisted cognitive goal referencing canonical mission | PARTIAL |
| Reflection | no cognitive complaint record | user-reported observation, suspected cause and deduped proposal | IMPLEMENTED |
| Self model | absent | scoped persisted operational view, no invented improvements | FOUNDATION ONLY |
| Unified memory | separate stores | reuse long_term_memory and cognitive/research references | PARTIAL |
| Learning | existing domain pipeline | bounded supplied content, provenance, duplicate/conflict, proposed only | PARTIAL |
| Knowledge gap | domain-specific | goal-scoped durable open gap | FOUNDATION ONLY |
| Planner | existing AgentPlanner | scoped active goal delegates to existing policy; does not execute | FOUNDATION ONLY |
| Proactive | domain-specific | repeated-response proposal dedupe (no repeat creation while present) | PARTIAL |
| Workspace | absent | namespace/domain project identity and reuse, no deletion | FOUNDATION ONLY |
| Tool registry | existing tools | capability metadata; declaration is not verified evidence | FOUNDATION ONLY |
| Research Brain | canonical research | retained; generic continuation only resolves an existing mission/goal | IMPLEMENTED |
| Web concurrency | one shared connection/server | four workers, per-request connections, one nonblocking chat slot | IMPLEMENTED |
| Cross-domain comparison | isolated domain state | shared conversation plus requested Binance snapshot; no common risk valuation | PARTIAL |

The bounded learner accepts already acquired text only. URL/document/image types
label the supplied data; it does NOT fetch/read those formats or extract trusted
claims. Different content on the same scoped topic is conservatively flagged as
a potential conflict, not automatically proven contradictory. All-source memory
federation, trusted promotion integration, generic non-research goal execution,
tool-need test-plan generation and proactive loss/tool-failure monitoring are
DEFERRED pending domain-specific evidence and authority contracts. The proactive
proposal remains deduplicated indefinitely; time-based re-evaluation is not added.

## Conversation and access contract

User text remains separate from `structured_context`. A Binance snapshot is
bounded display data, explicitly not an exchange requery or validation evidence.
It never enters promotion or strategy mutation. User feedback is validated only
as a user preference, not market knowledge. Goals use session scope; preferences
use user scope. Anonymous Web callers default to session identity. Cookie-based
browser identity is not authentication or cross-device account linking.

The Dashboard uses a stable HttpOnly/SameSite cookie, raw message proxy, 45-second
timeout, typed failure responses and no automatic retries. A timeout does not
cancel an already accepted server operation; a future request-status/idempotency
contract is still needed for long-running production research.

## Acceptance limitations

Local deterministic tests use temporary DBs and fake external clients. Browser
QA uses a static localhost preview (no trading bot, exchange or research provider),
so its displayed backend-disconnected error is expected. Real mobile keyboard,
authenticated multi-device continuity, live provider latency and VPS/Telegram
acceptance are PENDING PRODUCTION VERIFICATION. Existing approval controls are
preserved; no new cross-domain chat approval card or apply authority is added.

## Known independent issue

Quantity floor can reduce actual Binance notional below 5 USDT (-4164).
Trading sizing changes are explicitly excluded from this project.
