# Gaon Agent Foundation V2 (PR #214)

## Why this change

In production, ordinary conversation with Gaon fails. "이름이 뭔가요", "오늘 날씨는
어떤가요", an Instagram URL with "이건 어때요?" all return the same canned string
("말씀해 주신 불편을 확인했습니다…") - a *complaint acknowledgement* that was being
reused as the answer to any natural-language turn. "무엇을 할 수 있나요?" returned a
fixed five-line list of example prompts. A message that asked two things answered
only one.

The long-term goal is for Gaon to be a *Conversational + Multimodal + Research +
Self-Improving AI partner*. PR #214 is the **foundation**: it makes genuine
conversation work, grounds Gaon in an honest picture of its own abilities, and lays
down the typed seams (capability registry, tool / multimodal / evidence / developer
boundaries) that #215-#219 build on - **without** adding any real web / vision /
video provider, any self-code-modification, or any production / trading authority,
and without regressing the #213 read-only mission invariance or the execution
safety boundary.

## Root cause

Both Telegram (`TelegramConversationAgent`) and Web (`GaonWebChatAdapter`) call one
function: `LLMConversationBrain.respond` -> `_generate` in
`src/gaon/runtime/llm_conversation.py`.

In `_generate` the LLM provider is the **last** resort. Before it, a large
deterministic gauntlet runs - `_try_conversational_mvp` alone is ~1000 lines of
`if <keyword predicate>` branches. `classify_conversational_route`
(`conversational_mvp.py`) maps anything that "looks like natural language" to
`GENERAL_CONVERSATION`, and `_try_conversational_mvp` answered that intent with
`render_general_conversation()` (the complaint string) unless the text happened to
contain a KRX symbol or one of a few research-topic tokens. `render_help()` was a
hard-coded example list. `_generate` classified a multi-question turn once, as a
whole, so the first question was dropped.

Two fixture-backed tools (`weather_current`, `web_search`) are registered but
return demo payloads; nothing marked them as non-production, so a model could
fabricate "current" answers from them.

## Architecture

### Before

```
respond() -> _generate()
  binance snapshot -> pure greeting -> cognitive feedback -> approval gate
  -> _try_conversational_mvp()      # ~1000 lines of keyword branches
        GENERAL_CONVERSATION -> canned complaint string        <-- bug
  -> _try_authoritative_research_tool -> _try_multi_result_synthesis
  -> _try_deterministic_tool -> _try_follow_up_tool
  -> LLM provider (last resort)
```

### After

```
respond() -> _generate()
  binance snapshot -> pure greeting -> cognitive feedback -> approval gate
  -> GaonTurnRouter (NEW thin seam)
        MULTI_INTENT              -> split, route each segment, recompose
        MULTIMODAL / URL / CURRENT_INFO limitation
                                 -> honest capability-registry reply (no fabrication)
        PASS_THROUGH             -> everything else, unchanged
  -> _try_conversational_mvp()
        GENERAL_CONVERSATION:
          low-content complaint  -> canned honest feedback (unchanged)
          everything else + LLM  -> return None -> LLM path
  -> ... existing tail unchanged ...
  -> LLM provider, prompt grounded with capability_prompt_summary()
       provider error/timeout -> short honest persona fallback (unchanged text)
```

`GaonTurnRouter` never re-implements mission/research routing: for those lanes it
returns `PASS_THROUGH` and today's code runs. It only *owns* the lanes the legacy
pipeline mis-served. It holds no state and grants no capability.

## New package: `src/gaon/runtime/gaon_agent/`

| Module | Responsibility |
|---|---|
| `capabilities.py` | `Capability`, `CapabilityState` (AVAILABLE / UNAVAILABLE / APPROVAL_REQUIRED / FORBIDDEN), `SafetyClass`, `CapabilityRegistry`, `default_capability_registry()` (the single source of truth), `capability_prompt_summary()` (grounding block for the system prompt). Unknown ids fail closed to UNAVAILABLE. |
| `needs.py` | `RequestedGoal`, `NeedAssessment`, `assess_from_registry()` - partitions a goal's required capabilities and recommends a next step. Full blocker-diagnosis engine is #215. |
| `turn_router.py` | `GaonTurnRouter`, `TurnLane`, `RoutedTurn` + the deterministic limitation renderers. |
| `multi_intent.py` | `segment_turn()` - splits **only** on a blank line or an explicit enumerated list, each segment must be an independent short ask, total <= 300 chars, <= 3 segments. `recompose_answers()`. |
| `multimodal.py` | `Modality`, `describe_multimodal_request()` - recognises "look at this image/video/pdf" requests. All modalities map to an UNAVAILABLE capability in #214. |
| `tools.py` | `tool_capability_views()` - read-only projection of the existing `ToolRegistry`; flags `weather_current` / `web_search` / `news_search` / `market_data` / `exchange_rate` etc. as fixture-backed, not production. |
| `evidence.py` | `SourceRef` / `Observation` / `Claim` / `EvidenceRecord` (immutable, provenance mandatory, `VerificationState.UNVERIFIED` by default), `EvidenceIngestor` Protocol, `NullEvidenceIngestor` (refuses - pipeline is #218). |
| `developer_boundary.py` | `DEVELOPER_AGENT_CAPABILITIES` vs `FORBIDDEN_IN_AGENT_LAYER` (disjoint), `assert_not_privileged()`. |

## Changes to existing files

* `llm_conversation.py` - build `_capability_registry` / `_turn_router` /
  `_capability_summary` in `__init__`; call `_route_agent_turn` in `_generate`
  after the approval gate; `_base_prompt` takes `capabilities=`; the
  `GENERAL_CONVERSATION` branch defers to the LLM unless
  `is_low_content_complaint`; a bare "why/explain" knowledge question with no
  backward reference (`_references_prior_answer`) also defers to the LLM instead
  of the "no previous result" notice.
* `conversational_mvp.py` - `is_low_content_complaint()` (structural malfunction /
  absence / regret detector); `render_help()` rewritten as an honest capability
  overview.

No DB migration. No config change. No new dependency.

## Capability truth table (PR #214)

| id | state |
|---|---|
| GENERAL_CONVERSATION, RESEARCH_MISSION_READ, STRATEGY_STATUS_READ, MARKET_DATA_READ | AVAILABLE |
| RESEARCH_MISSION_RUN | APPROVAL_REQUIRED |
| WEB_SEARCH, URL_FETCH, DOCUMENT_READ, IMAGE_VISION, VIDEO_METADATA, VIDEO_TRANSCRIPT, VIDEO_FRAME_ANALYSIS, EVIDENCE_INGEST, EVIDENCE_VALIDATE, REPOSITORY_READ, CODE_MODIFY_DEV, TEST_RUN, GIT_COMMIT, GIT_PUSH, PULL_REQUEST_CREATE | UNAVAILABLE |
| PRODUCTION_DEPLOY, MAIN_MERGE, PRODUCTION_DB_WRITE, SYSTEMD_CONTROL, ARBITRARY_SHELL, TRADING_EXECUTION, LIVE_SWITCH, CHAMPION_PROMOTION | FORBIDDEN |

## Safety boundary (unchanged, regression-tested)

* Conversation autonomy != execution autonomy. `_requires_manual_boundary` /
  `safety_warning` still bypass the provider; any order / approval keyword in a
  turn - including one segment of a multi-intent turn - forces the whole turn
  through the deterministic boundary.
* Learning != truth. An external claim is an `EvidenceRecord` with
  `VerificationState.UNVERIFIED`; provenance is mandatory (fail closed);
  ingestion is not wired (`NullEvidenceIngestor` refuses).
* #213 read-only invariance: `conversation_integrity.py` is untouched; the seam
  never calls `extract_or_update_mission` / `_remember_mission` / a research
  execution path; multi-intent sub-turns run with `is_system_turn=True`.
* The LLM cannot grant itself a capability - the registry is code-defined and the
  router refuses to assert an UNAVAILABLE / FORBIDDEN capability as done.

## Tests

Unit: `tests/unit/test_gaon_agent_capabilities.py`,
`test_gaon_agent_turn_router.py`, `test_gaon_agent_multi_intent.py`,
`test_gaon_agent_evidence_foundation.py`.
Integration: `tests/integration/test_gaon_agent_foundation_web.py`,
`test_gaon_agent_foundation_telegram.py` - both transports, covering spec
section 23 groups (general conversation, current-info, URL, multimodal, mission,
context switch, multi-intent, capability, evidence, safety).
