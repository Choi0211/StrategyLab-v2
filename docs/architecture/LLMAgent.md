# Gaon LLM Agent Architecture

Gaon LLM Agent layers provider-backed conversation, native tool calling, multi-turn memory, and safe planning over the existing StrategyLab runtime.

Flow:

1. Telegram or CLI request enters the conversation runtime.
2. Context orchestration builds bounded verified context.
3. Provider may request structured read-only tool calls.
4. `SafeToolExecutor` validates and executes only registered tools.
5. Tool results are persisted with freshness metadata.
6. Provider or deterministic fallback synthesizes a Korean response.
7. Complex safe requests can be decomposed by `AgentPlanner`.

Allowed planner steps are `READ_TOOL`, `CONTEXT_LOOKUP`, and `SYNTHESIZE`. Approval operations stop at `REQUIRES_HUMAN_APPROVAL`.
