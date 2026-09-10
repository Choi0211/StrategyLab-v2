# Gaon Capability & Need Registry - Runtime Truth & Blocker Diagnosis

Roadmap item **#215** (`GaonAgentRoadmapV2.md`). Extends the PR #214
foundation (`GaonAgentFoundationV2.md`); does **not** replace it and does
**not** add a real web / vision / cloud-LLM provider or any paid feature.

## Why this change

`default_capability_registry()` statically declares
`GENERAL_CONVERSATION = AVAILABLE`. But the production topology for natural
conversation is:

```
Gaon VPS  ->  Tailscale  ->  user PC  ->  Ollama / qwen3:8b
```

So when the user's PC or Ollama is off, natural LLM conversation is
genuinely unusable even though it is still *configured* available and
*policy* allowed. Before this change, an identity / small-talk turn in that
state fell through to a generic deterministic reply
(`persona_text` / `_provider_unavailable_message`) that reads as *"Gaon did
not understand the question"* - and `RoutingAssistantProvider` silently
swallowed the dead-provider error and handed back deterministic persona
text with only a warning.

## The distinction this introduces

**Configured capability** (policy, deterministic, code-defined) is kept
separate from **runtime availability** (operational, observed):

| dimension | owner | values |
|---|---|---|
| configured state | `CapabilityRegistry` (unchanged) | `AVAILABLE` / `UNAVAILABLE` / `APPROVAL_REQUIRED` / `FORBIDDEN` |
| runtime availability | `ProviderRuntimeMonitor` (new, observational) | `AVAILABLE` / `DEGRADED` / `UNAVAILABLE` / `UNKNOWN` |

`CapabilityState` is untouched. The new layer is additive and lives in
`src/gaon/runtime/gaon_agent/runtime_status.py`.

### Invariants

* **Policy dominates.** `ProviderRuntimeMonitor.observe()` can return
  `RuntimeAvailability.AVAILABLE` **only** when the configured state is
  `AVAILABLE`. For a `FORBIDDEN` or `APPROVAL_REQUIRED` capability it does
  not even consult provider health - it returns `UNAVAILABLE` with reason
  `POLICY_NOT_AVAILABLE`. `TRADING_EXECUTION` stays `FORBIDDEN` whether the
  network is up or down.
* **Operational != policy.** "the provider is offline" is its own
  `RuntimeReason` (`PROVIDER_UNREACHABLE` / `PROVIDER_TIMEOUT` /
  `PROVIDER_DISABLED`); it never overwrites or masquerades as a policy
  state.
* **Runtime only ever narrows.** A configured-`AVAILABLE` capability can be
  observed runtime-unavailable; nothing is ever promoted.
* **No permission is granted here.** Nothing an LLM emits reaches the
  registry or the monitor. "mark `TRADING_EXECUTION` available" is just a
  `FORBIDDEN` capability requirement and stays blocked. Privileged
  execution permission remains owned by the deterministic safety
  controller.
* **Cheap / bounded.** No health request is issued from this layer. The
  monitor reuses the outcome of the assistant-provider call the
  conversation already makes, in a bounded-TTL cache
  (`DEFAULT_OBSERVATION_TTL_SECONDS = 90`). Older than the TTL, or no
  signal at all, is `UNKNOWN` - never a guessed `AVAILABLE`.
* **Fail closed / honest degradation.** Observation `detail` and every
  user-facing string are secret-, URL- and Tailscale-IP-free. If the
  provider is down, StrategyLab services are unaffected.

Only `GENERAL_CONVERSATION` is provider-backed
(`PROVIDER_BACKED_CAPABILITIES`); every other capability is served by
in-process read models and is therefore never affected by provider health.
A future PR that wires a real `WEB_SEARCH` / `URL_FETCH` provider adds its
id to that set.

## Runtime capability model

```
CapabilityRuntimeObservation
  capability_id
  availability : RuntimeAvailability  (available | degraded | unavailable | unknown)
  provider     : str | None
  observed_at  : ISO8601 UTC | ""
  reason       : RuntimeReason
  detail       : str   # short, user-safe; never provider internals
  source       : RuntimeObservationSource  (provider_call | health_probe | static)
```

`ProviderRuntimeMonitor`:

* `record_success(provider, now, latency_ms=None)` / `record_failure(provider,
  now, error_type)` / `record_disabled(provider, now)` - called by
  `LLMConversationBrain._generate` on the provider call it already makes
  (both the direct `ProviderError` path and the
  `RoutingAssistantProvider` "fallback warning" path).
* `observe(capability_id, now, configured_state) -> CapabilityRuntimeObservation`
* `resolve_runtime_observations(registry, monitor, now)` and
  `general_conversation_runtime(registry, monitor, now)` are the read
  helpers.

`error_type -> observation`: any string containing `timeout` -> `DEGRADED` /
`PROVIDER_TIMEOUT` (the provider may be up, just slow); `disabled` ->
`UNAVAILABLE` / `PROVIDER_DISABLED`; anything else -> `UNAVAILABLE` /
`PROVIDER_UNREACHABLE`.

## NeedAssessment / blocker diagnosis

`gaon.runtime.gaon_agent.needs`:

* `assess_from_registry()` is **unchanged** (policy partition only).
* `NeedAssessment` gains two fields, both defaulting empty so every existing
  construction is untouched: `runtime_unavailable_capabilities` and
  `blockers: tuple[Blocker, ...]`. `is_fulfillable_now` additionally
  requires both to be empty.
* `diagnose(goal, registry, *, runtime_observations=None, missing_user_input=(),
  missing_data=(), missing_evidence=())` builds on `assess_from_registry`
  and produces a typed, hardest-first `Blocker` list.

`BlockerKind`:

```
CAPABILITY_UNAVAILABLE   provider_offline (PROVIDER_OFFLINE)
PROVIDER_TIMEOUT         PROVIDER_DEGRADED
CONFIGURATION_DISABLED   MISSING_USER_INPUT
MISSING_DATA             MISSING_EVIDENCE
APPROVAL_REQUIRED        FORBIDDEN_BY_SAFETY
CODE_CHANGE_REQUIRED
```

Order: `FORBIDDEN_BY_SAFETY` -> `CAPABILITY_UNAVAILABLE` -> operational
provider blockers -> missing user input / data / evidence ->
`APPROVAL_REQUIRED`. `diagnose` never promotes a missing / approval /
forbidden capability, and runtime state can only move a capability out of
`available_capabilities` into `runtime_unavailable_capabilities`.

## User-facing behaviour

| turn | Ollama online | Ollama offline |
|---|---|---|
| "이름이 뭐예요?" | LLM-first conversation | route `conversation_runtime_unavailable`: *"지금은 대화용 AI 모델에 연결할 수 없어 자유로운 일반 대화는 제한됩니다. 연구 미션·전략 상태 확인 같은 서버 기능은 정상 사용할 수 있습니다."* - never the legacy "이해하지 못했습니다", never a stale research subject |
| "무엇을 할 수 있나요?" | `render_help()` (registry-grounded) | `render_help()` + one runtime-truth sentence; server-native reads still listed as available |
| "오늘 날씨는?" | `conversation_capability_limited_current_info` | unchanged |
| "이 링크 분석해줘 https://…" | `conversation_capability_limited_url` | unchanged |
| "단타 전략 연구 지금 어때요?" | authoritative `ResearchMission` read | **same** authoritative read - `RESEARCH_MISSION_READ` is not provider-backed |
| "왜 멈췄어요?" | authoritative blocker explanation | **same** - stale-subject regression stays green |
| "이름이 뭐예요? \n 단타 연구는 왜 멈췄어요?" | both answered | segment 1 = honest LLM-unavailable, segment 2 = authoritative blocker; one unavailable capability does not fail the whole turn |
| "삼성전자 100주 매수 주문 승인해줘" | deterministic approval gate, provider not consulted | **identical** - provider health is irrelevant to the safety gate |

The timeout variant keeps a "지연 / 다시 시도" phrasing so the #214
`test_provider_timeout_falls_back_to_a_short_honest_reply` regression still
holds.

The LLM system prompt is unchanged: when the provider is up we reach it and
the static capability summary is accurate; when it is down we never reach
it, so there is nothing to inject.

## Principles recorded

* **Conversation autonomy != execution autonomy.**
* **Runtime availability != permission.** A capability being observed
  reachable grants nothing; a capability being observed unreachable revokes
  no policy.
* **Provider online != privileged authority.**
* **Learning != truth. LLM output != permission.**
* `#214`'s final live Telegram E2E (real PC Ollama) is **still pending** -
  the PC is currently off. This work is developed and tested against an
  injected fake provider and does **not** discharge or bypass that
  acceptance.

## Files

New: `src/gaon/runtime/gaon_agent/runtime_status.py`.
Changed: `gaon_agent/__init__.py` (exports), `gaon_agent/needs.py`
(additive `Blocker` / `BlockerKind` / `diagnose` + two `NeedAssessment`
fields), `runtime/llm_conversation.py` (monitor field; record success /
failure on the provider call; honest `conversation_runtime_unavailable`
reply; runtime-truth sentence on the help / status answers).

No DB migration. No config change. No new dependency.

## Tests

Unit: `tests/unit/test_gaon_agent_runtime_truth.py` - monitor, observation,
`classify_provider_error`, `diagnose`, and the policy-dominance /
no-capability-grant invariants.
Integration: `tests/integration/test_gaon_capability_runtime_truth.py` -
Web + Telegram: identity offline honest reply (no stale 000370 / 005930),
timeout retry phrasing, mission / blocker reads survive offline, capability
answer reflects runtime truth, URL / current-info lanes unchanged,
multi-intent partial fulfilment, safety gate unaffected, no mission
mutation from read-only / capability queries.
