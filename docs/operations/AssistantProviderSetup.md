# Assistant Provider Setup

Status: optional and disabled by default

The assistant provider is guarded by explicit configuration. Tests use fake transports and do not call real networks.

## Environment Variables

- `GAON_ASSISTANT_ENABLED`
- `GAON_ASSISTANT_PROVIDER`
- `GAON_ASSISTANT_API_KEY`
- `GAON_ASSISTANT_BASE_URL`
- `GAON_ASSISTANT_MODEL`
- `GAON_ASSISTANT_TIMEOUT_SECONDS`
- `GAON_ASSISTANT_MAX_OUTPUT_TOKENS`

Do not commit real API keys or `.env` files.

## Current Providers

- `deterministic`: no network, safe fallback.
- `openai-compatible`: standard-library HTTP client for future execute-mode use.

## Runtime Behavior

- Provider disabled or unavailable: rule-based fallback.
- Provider timeout or malformed response: fallback.
- Approval, order, execution, policy, and memory mutation requests bypass provider.
- Provider output is validated before returning to Telegram.

## Not Implemented

- Real OpenAI SDK dependency.
- Live API smoke test in CI.
- Automatic memory writes.
- Automatic approval.
- Trading or broker execution.
