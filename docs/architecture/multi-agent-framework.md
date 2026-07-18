# Multi-Agent Execution Framework

Status: Sprint 37

The Multi-Agent Execution Framework consumes an `ExecutivePlan` from Sprint 36 and routes one bounded agent invocation through an explicit registry and dispatcher.

This sprint implements the execution foundation only. It does not add scheduler automation, daily research automation, Telegram-triggered execution, broker execution, KIS integration, or automatic approval.

## Contracts

- `Agent`: common protocol for deterministic agents.
- `AgentRequest`: bounded request passed to an agent.
- `AgentExecutionContext`: plan, request, config, correlation, and run metadata.
- `AgentResult`: structured output with agent name, status, output, error, metadata, started time, and completed time.
- `AgentCapability`: explicit capability declaration.
- `AgentStatus`: `succeeded`, `failed`, `blocked`, or `requires_approval`.

## Registry

`AgentRegistry` requires explicit registration. It rejects duplicate names, rejects unknown lookups, performs stable-name lookup, and returns deterministic name ordering.

There are no arbitrary dynamic imports and no plugin loading path in Sprint 37.

## Dispatcher

`AgentDispatcher` consumes an `ExecutivePlan` and invokes one selected agent. It:

- validates the selected agent
- validates required capabilities from plan tools
- creates `AgentExecutionContext`
- isolates agent failures
- returns `AgentResult` instead of crashing the runtime
- preserves correlation through plan and request IDs
- blocks `approval_required` plans without executing protected actions

## Initial Agents

- `ResearchAgent`: uses deterministic internal research planning only.
- `CodingAgent`: inspection-only; does not execute shell commands or mutate files.
- `MemoryAgent`: read-only boundary; does not promote unapproved knowledge.
- `TradingAgentPlaceholder`: non-executing placeholder for architecture compatibility.

## Events and Metrics

Lifecycle events:

- `AgentExecutionStarted`
- `AgentExecutionCompleted`
- `AgentExecutionFailed`
- `AgentExecutionBlocked`

Metrics:

- `gaon_agent_executions_total`
- `gaon_agent_execution_failures_total`
- `gaon_agent_execution_blocked_total`

## CLI Smoke

```powershell
py -3.11 -m gaon.runtime.cli agent-run --agent research --request "research context"
py -3.11 -m gaon.runtime.cli agent-run --agent coding --request "inspect code" --json
py -3.11 -m gaon.runtime.cli agent-run --agent memory --request "memory lookup"
```

These commands are deterministic local smoke checks and do not call live external services.
