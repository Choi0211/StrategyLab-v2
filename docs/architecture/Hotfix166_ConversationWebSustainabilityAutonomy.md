# Hotfix #166: Conversation Routing, Web Chat Lifecycle, Sustainability Objective, Autonomy

Status: Implemented (backend); Web Chat scroll/follow/new-message-indicator UX is a known blocker - see "Known limitations" below.

## Root Causes (Section 1: Conversation Routing Recovery)

1. **`is_mission_candidate_read_request` was gated on a mission already
   existing.** `LLMConversationBrain._try_conversational_mvp` only
   consulted this (already-correct, already typo/spacing-tolerant)
   read-only-question classifier inside `if mission is not None and
   mission.universe_scope is not SINGLE_SYMBOL: ...`. A research-status
   question asked *before* any mission existed ("단타 전략은 잘 연구되고
   있나요?") therefore never reached it, and fell through to the generic
   `GENERAL_CONVERSATION` natural-language fallback.
2. **The same question mutated mission state just by being asked.**
   `extract_or_update_mission`'s `research_intent` inference treated any
   text mentioning a research verb ("연구") plus a strategy family
   ("단타") as a real research instruction - including a pure status
   *question*, which silently created a new `SINGLE_SYMBOL` mission with
   `strategy_family="short_term_daytrade"` out of a read-only question.
3. **Research-status and runtime-status questions collided once a mission
   existed.** A pre-existing branch (Patch 8.2, "지금 뭐 연구하고
   있어?") answered *any* `STATUS_QUERY`-classified message with mission/
   candidate status whenever a mission with candidates existed - including
   "현재 동작 하고 있나요?", a runtime/availability question that also
   classifies as `STATUS_QUERY` (Hotfix #165's `is_availability_question`).
4. **No typo tolerance for the runtime-status "state" tokens.** "동적"
   (a common typo of "동작") did not match `is_availability_question`'s
   exact-substring check.

## Changes (Section 1)

- `is_mission_candidate_read_request` is now consulted even when
  `mission is None`, returning an honest "no active Research Mission"
  message (new route `conversation_research_status_no_mission`) instead
  of falling through to feedback.
- `extract_or_update_mission`'s verb+family research-intent signal now
  excludes text that itself already classifies as
  `is_mission_candidate_read_request` (a read-only question) - the
  explicit-scope signals (market-wide, ≥2 explicit symbols, target count,
  generic continuation) are untouched and still establish real intent
  regardless of phrasing.
- The mission-candidate-status branch (Patch 8.2) now excludes text that
  matches `is_availability_question` (renamed from `_is_availability_
  question` and exported), so a runtime/availability question is never
  reinterpreted as a research-status question just because a mission
  happens to exist.
- `is_availability_question`'s state-token matching gained a small,
  narrowly-scoped typo-tolerance helper (`_typo_tolerant_contains`,
  bounded Levenshtein distance ≤1, same idea as `research_mission.py`'s
  existing continuation-phrase typo tolerance) applied to exactly one
  token ("동작") - NOT the whole state-token list, because "가능" sits
  one edit away from "가온" (Gaon's own name, also a subject token),
  which would otherwise misclassify ordinary greetings like "안녕하세요
  가온" as a runtime-status question (caught by two previously-passing
  tests going red during implementation; fixed by narrowing scope, not by
  removing the tolerance).

No exact-string patch was added; all three fixes are structural
(precedence/gating changes on already-existing, already-generalized
classifiers).

## Section 2: Web Chat UX

**Backend implemented and tested:** `GET /gaon/chat/messages` (paginated,
`limit`/`before` cursor over `conversation_messages`, backward compatible
with `SQLiteConversationRepository.list_messages`'s existing most-recent-N
behavior when no cursor is given).

**Known blocker - no frontend exists in this repository.** Investigation
confirmed `StrategyLab-v2` has zero HTML/JS/CSS anywhere; the actual chat
widget is a separate sibling deployment (the Binance trading bot's
dashboard, `/opt/binance-trading`, not part of this checkout) that calls
this repo's HTTP API. Scroll-to-latest on open, follow-mode while scrolled
to the bottom, respecting the user having scrolled up, and a "new
messages ↓" control are all client-side behaviors that must be
implemented in that separate repository against the pagination endpoint
this hotfix adds - they cannot be implemented from within
`StrategyLab-v2`. This is reported honestly rather than fabricated.

## Section 3: Conversation Lifecycle

New module `gaon.runtime.conversation_lifecycle` (list/archive/unarchive/
delete-messages/paginate), wired into `web_api.py` as:

- `GET /gaon/chat/conversations?user_ref=...&include_archived=...`
- `GET /gaon/chat/messages?session_ref=...&user_ref=...&limit=...&before=...`
- `POST /gaon/chat/conversations/archive` / `.../unarchive`
- `POST /gaon/chat/conversations/delete` (requires `confirm: true`, 400
  otherwise)

**Durable-state separation (the important guarantee):** ResearchMission/
StrategyCandidate state lives inside the conversation's own
`conversation_sessions.metadata_json` row (the `conversation_mvp.
research_mission` key), not in `conversation_messages`. "Delete
conversation" here means exactly: purge `conversation_messages` (+ its two
dependent per-message tables, `conversation_summaries` and
`conversation_tool_results`) for that `session_id`, and mark the session
`status="deleted"` (excluding it from listing) - the `conversation_sessions`
row itself, and therefore its `metadata_json`, is never touched. Cognitive
Core state (`cognitive_records`) is a structurally separate table with no
foreign key relationship to conversation messages at all, so it cannot be
reached by this deletion regardless.

**No schema migration.** "Archive" reuses the existing
`conversation_sessions.status` column (previously only ever "active").
"List" reuses the existing `idx_conversation_sessions_user(user_ref,
updated_at)` index. Pagination adds only a new WHERE clause over the
existing `idx_conversation_messages_session` index. Ownership is checked
(`session.user_ref` must match the caller's `user_ref`) before any
archive/delete/list-messages operation; an unowned `session_ref` is
reported as 404, never revealing whether it exists.

## Section 4: Sustainability & Growth Objective

New module `gaon.cognitive.sustainability`. A single durable
`CognitiveRecord` (type `GOAL`) is persisted at a reserved system
namespace (`system:gaon-sustainability`), auto-bootstrapped (idempotent -
a no-op after the first call ever made against a database) whenever
`LLMConversationBrain` constructs its `CognitiveOrchestrator`. Its payload
carries the full meaning text plus two **structured** fields consumers can
check programmatically rather than re-parsing prose:

- `forbidden_justifications`: `risk_increase`, `leverage_increase`,
  `validation_threshold_relaxation`, `fabricated_evidence`,
  `approval_bypass`, `champion_auto_promotion`, `strategy_auto_apply`,
  `live_order_execution`, `unauthorized_fund_use`.
- `sustainability_dimensions`: `return`, `drawdown`, `volatility_risk`,
  `robustness`, `evidence_quality`, `transaction_cost_sensitivity`,
  `live_vs_backtest_divergence`, `long_term_consistency`.

**Isolation guarantee (verified, not assumed):** the reserved system
namespace can never collide with a real user/session namespace -
`SQLiteCognitiveRepository.put`'s existing namespace+record_type identity
lock (unchanged by this hotfix) makes this a hard technical guarantee.
`CognitiveOrchestrator.retrieve()` itself is completely unmodified - a
user/session namespace query never returns the system objective, and
creating it never reads or writes any user namespace. Tested for restart
survival, idempotency (a second `ensure` call does not bump
`updated_at`), and namespace isolation in both directions.

This is durable Cognitive Core state, not a system-prompt string - it
survives process restarts and new conversations because it is ordinary
SQLite state in the same `cognitive_records` table every other Cognitive
Core record uses.

## Section 5: Self-Directed Autonomous Research

Investigation confirmed the "decide the next research action from cycle
results" decision loop the spec describes (root-cause → hypothesis →
evidence → experiment → validation → compare → reject/retain → next
hypothesis) is **already implemented** by the existing
`gaon.knowledge.strategy_candidate.next_blocker_driven_research_action`
state machine (13-branch decision table already covering EXPAND_SAMPLE,
RUN_OOS/REGIME/WALK_FORWARD/COST_STRESS/SENSITIVITY/MONTE_CARLO,
ROTATE_CANDIDATE, economic-viability-gated promotion) and was already
exercised every tick by Hotfix #165's `AutonomousResearchRuntimeWorker`
via the exact same `LLMConversationBrain.respond()` continuation path a
live Telegram turn uses. `DailyResearchPipeline`/`deterministic_research_
plan` is still never used - confirmed unchanged from #165.

**What this hotfix adds:** integration tests proving the *already-real*
capability end to end without weakening or duplicating it -
`test_repeated_ticks_self_direct_progress_without_any_new_user_message`
(four scheduled ticks, zero new user messages, real bounded work each
tick) and `test_restart_resumes_the_same_durable_mission_and_keeps_
advancing_it` (a fresh worker instance against the same store resumes -
never restarts - the same mission).

**Honestly not built:** the spec's example blocker "data unavailable →
alternate trusted source if configured" has no existing "alternate
trusted source" configuration concept anywhere in this codebase
(confirmed by investigation of `research_mission.py`/`strategy_candidate.
py`/the provider-acquisition-blocker path). Fabricating a fallback source
selector with no real second source to fall back to would be exactly the
kind of fake implementation the hotfix's own principles forbid. A
`provider_unavailable`-blocked mission remains honestly `BLOCKED` (already
the tested, correct behavior from Hotfix #165) rather than gaining an
invented recovery path.

## Section 6: Proactive Research Prioritization

New module `gaon.research.research_priority`
(`propose_research_priority`). Read-only; gathers real, already-computed
evidence from both domains and returns a **structured comparison**, never
a single forced verdict with an invented weighting formula:

- **KR**: `ResearchMission.status`/`blocked_reason`, the active
  candidate's real `candidate_remaining_blockers` - the exact same read
  models the mission-driven cycle itself uses.
- **Binance**: `gaon.adapters.binance.BinanceResearchReader.family_
  summary()` (real OOS walk-forward win-rate/return/drawdown/sample size,
  already exposed for the existing champion/challenger comparison path) -
  read-only, and reported as honestly `not_configured`/`no_research_data`
  when the file is absent, never substituted with synthetic data.

Both domains are surfaced with real evidence and structural flags
(`blocked`, `active_candidate_has_unresolved_blockers`,
`insufficient_sample`, `not_configured`, ...); a domain only appears in
`flagged_domains` when a real, already-computed signal says so. This
module never mutates anything and never reaches `gaon.adapters.trading`/
`strategy_execution`/`strategy_deployment`/`promotion_gate` (verified by a
static source-scan test) - it cannot influence Binance's live strategy in
any way, satisfying the StrategyLab/Binance safety boundary.

**Honestly not built:** live-vs-backtest performance divergence and
"repeated loss pattern vs. baseline" degradation detection do not exist
anywhere in this codebase (confirmed by investigation - `LiveFeedback`
tracks only order-mechanics counters, no backtest-expectation baseline is
stored anywhere reachable). Building a genuine (non-fabricated) version of
that signal requires new evidence plumbing that is a substantial, separate
feature: not implemented here, reported honestly rather than faked with
an invented threshold.

## Section 7 & 8: Human Gate / System Turn Isolation

Unchanged from Hotfix #165, reaffirmed by the full passing test suite
(including `#165`'s `MissionStatus.AWAITING_HUMAN_APPROVAL` hard-stop and
`is_system_turn` conversation-history/cognitive-memory isolation tests) -
nothing in this hotfix touches either mechanism.

## Section 10: Safety Release Check

New `gaon.runtime.web_api.production_conversation_lifecycle_durable_state_
release_check` (CLI: `gaon-production-conversation-lifecycle-durable-
state-release-check`). Seeds a real mission+candidate and a real user
Cognitive Core goal through a real session, snapshots real repository row
counts across `champion_registry`/`champion_history`/`promotion_requests`/
`promotion_decisions`/`approvals`/`strategy_deployment_*`/`strategy_
execution_*` before and after an archive → rejected-unconfirmed-delete →
confirmed-delete sequence, and asserts: all counts unchanged; the mission
and its candidate are still readable afterward; the user's Cognitive Core
goal is still readable afterward; the durable sustainability objective is
untouched (`updated_at` unchanged); messages are actually gone. Hotfix
#165's `production_autonomous_research_runtime_release_check` (real
before/after observation of the same table set, plus `llm_tool_audit.
risk_level` verification) is unchanged and still covers autonomous-worker
safety.

## Schema / Migration

None. See Section 3 above - archive/list/delete/paginate all reuse
existing columns/indexes.
