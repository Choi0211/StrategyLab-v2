# Hotfix: Research Director Planned Action -> Executor Handoff

Status: COMPLETE

## Context

Production Telegram showed an active Research Mission candidate (`KR-ST-003`,
volume-confirmed breakout) with 5 validated symbols and 81 cumulative trades.
The Research Director correctly reported the next priority as `RUN_REGIME`
because `regime_validation=partial`, but the next generic continuation
("연구를 계속해주세요") re-entered the generic robustness path and replayed the
same evidence instead of consuming that planned action as executor input.

## Root Cause

`LLMConversationBrain._try_candidate_robustness_cycle()` called
`autonomous_learning_research` directly. It persisted the resulting validation
stage status, but it did not compute the candidate's next blocker-driven action
before the next tool call, did not pass that action into the safe-tool request,
and treated action-label changes as progress. The Director action therefore
became presentation text rather than an execution handoff.

## Design

- `StrategyCandidateRecord` remains the durable authoritative state; schema v36
  is unchanged.
- `next_blocker_driven_research_action(candidate)` derives the next bounded
  action from persisted evidence:
  `RUN_OOS`, `RUN_REGIME`, `RUN_WALK_FORWARD`, `RUN_COST_STRESS`,
  `RUN_SENSITIVITY`, `RUN_MONTE_CARLO`, `EXPAND_SAMPLE`, `ROTATE_CANDIDATE`,
  or `REQUEST_HUMAN_APPROVAL`.
- Telegram robustness continuation now consumes that action by passing
  `planned_action` and `planned_action_reason` to the existing read-only
  `autonomous_learning_research` safe tool. No new research engine was added.
- The response records `action_executed`, the validation dimension, whether the
  stage changed, and the recomputed next action.
- Duplicate evidence identity is dimension-aware: same candidate/symbol with a
  new validation dimension can progress; exact same action/symbol/dimension/
  status records no progress and increments no-progress state.

## RUN_REGIME Trace

Turn 1:

- persisted state has `regime_validation=partial`
- planner returns `RUN_REGIME`, `reason=regime_blocker`

Turn 2:

- generic continuation consumes `RUN_REGIME`
- `autonomous_learning_research` receives `planned_action=RUN_REGIME`
- regime evidence is recorded from the existing validation output

Turn 3:

- next action is recomputed from updated candidate state
- if regime is resolved, `RUN_REGIME` is not repeated
- if no progress occurred, no-progress/stagnation accounting advances

## Safety

No live trading, KIS/Broker orders, Champion auto-promotion, approval bypass,
strategy mutation, fixture-as-real evidence, or fabricated metrics were added.
