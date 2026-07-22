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
GAON_ASSISTANT_MAX_OUTPUT_TOKENS=2048
GAON_ASSISTANT_MAX_CONTINUATIONS=2
GAON_ASSISTANT_MAX_TOOL_CALLS_PER_TURN=3
GAON_ASSISTANT_MAX_PLANNER_STEPS=5
GAON_ASSISTANT_MAX_REQUESTS_PER_MINUTE=12
GAON_ASSISTANT_MAX_CONTEXT_CHARS=4000
```

Future local endpoints such as Ollama-compatible proxies can use the same base URL/model pattern, but this repository does not require or install Ollama.

For local Ollama/Qwen3-style OpenAI-compatible endpoints, `2048` output tokens
is the default conservative recommendation for Telegram conversations. If the
host has enough memory and latency remains acceptable, operators may raise it
toward `4096`. The runtime rejects values below `64` or above `8192`, and
continuation is bounded by `GAON_ASSISTANT_MAX_CONTINUATIONS`.

`finish_reason=length` is treated as truncation. Gaon asks the provider for a
bounded continuation, merges non-duplicate text, and keeps any valid partial
answer if continuation fails. Hidden reasoning and chain-of-thought fields are
not surfaced to users.

## CLI Diagnostics

```bash
python -m gaon.runtime.cli assistant-provider-status
python -m gaon.runtime.cli agent-status
python -m gaon.runtime.cli agent-plan-history --db runtime.sqlite
python -m gaon.runtime.cli tool-chain-history --db runtime.sqlite
python -m gaon.runtime.cli llm-agent-release-check
python -m gaon.runtime.cli long-response-release-check
```

## Security Boundary

The LLM may interpret intent, request registered read-only tools, and synthesize Korean responses. It may not approve, deploy, trade, execute shell commands, run arbitrary SQL, read secrets, or bypass deterministic approval gates.
