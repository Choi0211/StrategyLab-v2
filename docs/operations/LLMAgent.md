# Gaon LLM Agent Operations

Status: Sprint 56-60 release hardening

## Provider Configuration

Use generic OpenAI-compatible settings:

```bash
GAON_ASSISTANT_ENABLED=true
GAON_ASSISTANT_PROVIDER=openai-compatible
GAON_ASSISTANT_BASE_URL=https://provider.example/v1
GAON_ASSISTANT_MODEL=your-model
GAON_ASSISTANT_API_KEY=never-commit-real-values
GAON_ASSISTANT_TIMEOUT_SECONDS=10
GAON_ASSISTANT_MAX_OUTPUT_TOKENS=500
GAON_ASSISTANT_MAX_TOOL_CALLS_PER_TURN=3
GAON_ASSISTANT_MAX_PLANNER_STEPS=5
GAON_ASSISTANT_MAX_REQUESTS_PER_MINUTE=12
GAON_ASSISTANT_MAX_CONTEXT_CHARS=4000
```

Future local endpoints such as Ollama-compatible proxies can use the same base URL/model pattern, but this repository does not require or install Ollama.

## CLI Diagnostics

```bash
python -m gaon.runtime.cli assistant-provider-status
python -m gaon.runtime.cli agent-status
python -m gaon.runtime.cli agent-plan-history --db runtime.sqlite
python -m gaon.runtime.cli tool-chain-history --db runtime.sqlite
python -m gaon.runtime.cli llm-agent-release-check
```

## Security Boundary

The LLM may interpret intent, request registered read-only tools, and synthesize Korean responses. It may not approve, deploy, trade, execute shell commands, run arbitrary SQL, read secrets, or bypass deterministic approval gates.
