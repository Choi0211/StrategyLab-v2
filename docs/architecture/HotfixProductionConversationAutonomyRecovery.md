# Hotfix: Production Conversation and Autonomous Research Runtime Recovery

Status: Implemented

## Context

Real production Telegram usage surfaced several related regressions in the
same window:

- Natural, ordinary Korean questions ("뭘 할 수 있나요?", "어떤 자원이
  필요한가요") fell through to the legacy deterministic UNKNOWN persona
  fallback instead of their own already-existing, already-correct
  classifiers.
- An explicit symbol reference outside the five curated blue-chip names
  (e.g. `071055`) was invisible to `route.symbols`, so a later bare
  follow-up ("백테스트해주세요") could silently drift onto a different,
  unrelated, fixture-backed default symbol.
- Pre-market briefings already rendered canonical `ResearchMission` state
  (`HotfixMorningBriefingResearchStateConsistency.md`), but post-market and
  unresolved-review briefings still said "추가 연구 없이 관찰을 계속합니다"
  / "현재 후속 조치가 필요한 연구가 없습니다" unconditionally, contradicting
  an ACTIVE mission the same conversation reported as ongoing.
- No background/scheduled path ever advanced a persisted ACTIVE
  ResearchMission - all research only ever happened synchronously inside a
  live Telegram turn.
- `strategy_hypothesis_space_exhausted` permanently BLOCKED a mission with
  no bounded recovery path, even when a STAGNANT candidate had stalled on
  cycle-count bookkeeping rather than genuine axis exhaustion.
- A Telegram reply never carried Telegram's own `reply_to_message_id`, so a
  user-turn answer and an unrelated scheduled briefing could both appear as
  plain top-level messages with no visible correlation to which request
  produced which reply.

## Root Causes

1. **Legacy blanket-token gate.** `LLMConversationBrain._try_conversational_mvp`
   had an early `if not _contains_supported_conversational_mvp_token(text)
   and route.intent not in {...}: return None` gate. The intent allowlist
   there predated `ConversationalMVPIntent.HELP` reliably matching natural
   phrasing (only the literal token `도움말` was in the token list, not
   "뭘 할 수"), and predated `GENERAL_CONVERSATION` and the new
   `RESOURCE_NEEDS_QUERY` intent entirely. A correctly-classified intent
   still hit this gate and fell through to the legacy `persona_text(Intent.
   UNKNOWN)` fallback (`route="rule_based"`).
2. **Symbol recognition gated on a 5-name allowlist.**
   `conversational_mvp.extract_symbol_entities` only recognized a 6-digit
   KRX code as an explicit symbol if it was also a key in `SYMBOL_NAMES`
   (005930/000660/005380/035420/051910). Any other real symbol was
   structurally invisible to `route.symbols`, which several scope-
   regression guards (e.g. `LLMConversationBrain.
   _mission_aware_continuation_fail_safe`) depend on to avoid falling back
   to stale/default conversational context.
3. **Post-market/unresolved-review briefings never read `ResearchMission`.**
   `PostMarketBriefing`/`compose_post_market_briefing`/
   `render_post_market_briefing_ko` (and the unresolved-review equivalents)
   had no `research_mission` field at all, unlike `PreMarketBriefing`.
4. **No background research worker existed.** Research only ever advanced
   from `LLMConversationBrain._try_mission_driven_research_cycle`, called
   synchronously from a live Telegram turn.
5. **STAGNANT candidate status is a deliberate terminal state.**
   `next_blocker_driven_research_action` unconditionally returns
   `ROTATE_CANDIDATE` for `StrategyCandidateStatus.STAGNANT`/`REJECTED`, so
   a mission that exhausted its bounded declarative strategy-family/rule-
   composition grammar (`expand_strategy_space_candidate` returning no
   candidate) stayed BLOCKED forever with no path back, even for a
   candidate that only stalled on cycle-count bookkeeping.
6. **`TelegramResponse` never set `reply_to_message_id`.** The contract
   already supported it (`TelegramBotApiClient.send_message(...,
   reply_to_message_id=...)`), but `TelegramRuntime.handle_message` never
   populated it, and `send_proactive_message` (used for scheduled
   briefings) never needed to.

## Design

### Routing precedence (Section 6 in the hotfix spec)

- Added `ConversationalMVPIntent.RESOURCE_NEEDS_QUERY` with a narrow,
  structural predicate `_is_resource_needs_question` (subject token ∩
  ask token, same shape as the existing `_is_availability_question`) -
  not a token-list expansion.
- Added `HELP`, `GENERAL_CONVERSATION`, and `RESOURCE_NEEDS_QUERY` to the
  intent allowlist in `_try_conversational_mvp`'s legacy blanket-token
  gate, so a message already correctly classified by
  `classify_conversational_route` is never discarded by an older,
  narrower token list. This is a precedence/allowlist fix, not a new
  keyword list.
- `LLMConversationBrain._render_resource_needs` answers "어떤 자원이
  필요한가요" only from real, already-persisted state: the active
  mission's `blocked_reason` (via the existing `mission_blocked_message`),
  or the active candidate's real `candidate_remaining_blockers`/
  `next_blocker_driven_research_action` (the same read models the
  mission-driven research cycle itself already consults). Never a
  provider-invented "compute/data" claim.

### Context/provenance integrity (Section 7)

- `extract_symbol_entities` now recognizes any well-formed 6-digit KRX
  code as an explicit symbol reference, falling back to the code itself
  as the display name when `SYMBOL_NAMES` has no curated Korean name for
  it. This directly fixes the reported `071055 -> 005930` regression: an
  explicit symbol outside the five curated names is no longer invisible
  to `route.symbols`.
- No new provenance framework was added; `gaon.runtime.research_grounding`
  (`contains_fixture_leakage`, `contains_unverified_fixture_metrics`,
  `strict_real_research_grounding_violations`) remains the single gate a
  tool result passes through before becoming user-facing text.

### Briefing consistency (Section 8)

- `PostMarketBriefing` and the unresolved-research-review renderer now
  accept an optional `research_mission: ResearchMissionBriefingState`,
  reusing `ResearchMissionBriefingState.from_mission` and
  `_render_research_mission_briefing_lines` - the exact same read model
  `PreMarketBriefing` already used.
- The "no follow-up" sentence in both is now explicitly scoped ("장중 실행
  이슈에서 파생된 후속 연구 항목은 없습니다." / "뉴스 기반 후속 조치가
  필요한 연구는 없습니다.") instead of a global claim, and a
  `[Research Mission]` section is appended whenever a mission exists -
  matching the pre-market briefing's shape.
- `DailyBriefingRuntimeWorker` now threads its existing
  `research_mission_provider` (`latest_research_mission_from_connection`)
  into the post-market and unresolved-review composers too, not only
  pre-market.

### Background autonomous research (Sections 4, 11, 12, 13)

New module: `gaon.runtime.autonomous_research_runtime`.

- **Real research path only.** `AutonomousResearchRuntimeWorker.tick()`
  advances the canonical Telegram-scoped mission
  (`session_id = f"telegram:{chat_id}"`, the same session binding
  `TelegramConversationAgent` uses) by calling
  `LLMConversationBrain.respond()` with a synthetic continuation request
  (`text="연구 계속해주세요"`, the same production-proven continuation
  phrase). `source="telegram"` and a `telegram:`-prefixed `message_id` are
  required for `_is_conversational_mvp_source` to route this through the
  real conversational-MVP pipeline - the exact same
  `_try_mission_driven_research_cycle` a live Telegram message triggers.
  **`gaon.runtime.daily_research.DailyResearchPipeline` (which composes
  `deterministic_research_plan`, a synthetic/deterministic fixture) is
  never used here and must never be wired into this or any other
  production autonomous-research path.**
- **Hard stop at the approval gate.** A mission at
  `MissionStatus.AWAITING_HUMAN_APPROVAL` (the codebase's name for the
  spec's READY_FOR_APPROVAL state), `COMPLETED`, or `CANCELLED` is never
  advanced. Only `ACTIVE` (and `BLOCKED`, for bounded recovery only) are
  touched.
- **Bounded hypothesis-space recovery.**
  `attempt_bounded_stagnation_recovery` reopens at most
  `max_candidates` (default 2) STAGNANT candidates per call, and only one
  that (a) stagnated purely on `validation_cycle_exhausted_without_progress`
  (the cycle-count bookkeeping threshold, not genuine axis exhaustion),
  (b) still has a real unresolved `candidate_remaining_blockers`, and (c)
  has not failed economic viability. It never creates a new strategy
  family/candidate identity - it only resumes that candidate's own
  already-declared, not-yet-finished validation work (OOS/regime/walk-
  forward/cost-stress/etc., via the existing
  `next_blocker_driven_research_action`). When no eligible candidate
  exists, the mission stays honestly BLOCKED with its real
  `blocked_reason` - never replaced with a fabricated "compute/data"
  explanation.
- **Durable, idempotent scheduling.** `AutonomousResearchRuntimeService`
  reuses the existing `gaon.runtime.scheduled_automation.
  ScheduledJobRepository` (the same table `daily_research`/
  `daily_briefing` already use) - `due()`/`claim_run()`/`complete_run()` -
  and reschedules the next tick by creating a new job row, mirroring
  `DailyBriefingScheduler.run_due()`'s shape. A restart simply resumes
  from the persisted `next_run_at`; no in-memory timer state exists.
- **Isolation.** Wired into `gaon.runtime.cli._runtime_tick` alongside
  (not instead of) the existing Telegram worker and
  `DailyBriefingRuntimeWorker`; a failure in any one worker is caught and
  reported per-worker and never prevents the others from ticking.
- **No trading/promotion path is reachable.** `LLMConversationBrain`'s
  mission-cycle methods never import `gaon.adapters.trading`,
  `strategy_execution`, `strategy_deployment`,
  `gaon.knowledge.promotion_gate`, or `human_gated_promotion` - verified
  by both static source inspection and the release check below.

### Response correlation (Section 9)

- `TelegramResponse` gained `in_reply_to: str | None`, set from the
  inbound `message.message_id` in `TelegramRuntime.handle_message` for
  every real user-turn reply (including the too-long-input fallback), and
  left `None` for `send_proactive_message` (scheduled briefings). `_send_
  with_retry` now passes `reply_to_message_id=response.in_reply_to`
  through the already-existing `TelegramClient.send_message` parameter.
  No new schema; a scheduled briefing can never render as a reply to an
  unrelated prior user message, and a user's own reply is now visibly
  threaded to their own message in Telegram.

## Explicit Boundaries (unchanged, reaffirmed)

- Autonomous research's maximum reachable state is
  `MissionStatus.AWAITING_HUMAN_APPROVAL` (READY_FOR_APPROVAL). Nothing in
  this hotfix approves, applies, promotes, deploys, or places an order.
- `gaon.runtime.daily_research.DailyResearchPipeline` and its
  `deterministic_research_plan` remain deterministic/synthetic and are
  **not** the production autonomous research path. Do not wire them into
  `AutonomousResearchRuntimeWorker` or any future background research
  entry point.
- Grounded runtime status ("VPS 기반인가요?", "현재 동작하나요?") is
  answered only from the existing `runtime_status` tool / structured
  state, never LLM inference.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-autonomous-research-runtime-release-check
```

Proves: an ACTIVE mission advances by exactly one bounded real research
tool call per tick; a mission at `AWAITING_HUMAN_APPROVAL` is never
advanced; a BLOCKED mission with no eligible recovery candidate stays
honestly BLOCKED; the scheduling service is idempotent; and
`strategy_mutated`/`order_executed`/`champion_promoted`/`approval_bypassed`
are all `False`.
