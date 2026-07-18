# Executive Planner

Status: Sprint 36

Executive Planner is Gaon's routing layer for deciding which safe planning path should handle a request. It produces a plan only. It does not execute agents, schedule jobs, trade, send Telegram messages, or call external tools.

## Contracts

- `ExecutiveRequest`: bounded user or system request metadata.
- `ExecutivePlan`: immutable routing result with schema versioning.
- `RoutingDecision`: `research`, `memory`, `runtime`, `human_review`, or `unsupported`.
- `AgentSelection`: selected conceptual agent boundary.
- `ToolSelection`: selected planning or inspection tool boundary.
- `ExecutivePlanner`: interface implemented by deterministic and provider-backed planners.

## Planner Modes

`DeterministicExecutivePlanner` uses local rule-based routing. It is the default CLI path and requires no provider, network, API key, scheduler, Telegram, broker, or private repository access.

`ProviderBackedExecutivePlanner` uses the existing Assistant Provider Registry to select a provider. Provider output must be bounded JSON and is validated into the same `ExecutivePlan` contract.

## Free-Only Enforcement

If the request or runtime configuration is in free-only mode, network or non-deterministic provider routing is rejected. Paid provider routing also requires `GAON_PAID_PROVIDER_ENABLED=true`; it is disabled by default.

## Approval Required

Requests that mention execution-capable or policy-changing actions are routed to `human_review` and include `approval_required=true`. This is a flag only. Sprint 36 does not implement approval execution or any downstream action.

## Event and Metrics

Every plan can be converted into an `ExecutivePlanCreated` durable event. Planner calls increment `gaon_executive_plans_total` with safe labels.

## CLI

```powershell
py -3.11 -m gaon.runtime.cli executive-plan --request "ORB 전략 연구해줘"
py -3.11 -m gaon.runtime.cli executive-plan --request "상태 알려줘" --json
```

The CLI appends the plan event to the configured runtime database and prints the inspected plan.
