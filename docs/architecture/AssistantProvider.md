# Assistant Provider

Status: Sprint 15 guarded provider integration

Assistant Provider is a replaceable response-generation boundary. It may draft text, but it cannot approve, place orders, mutate memory, change policy, or execute research.

## Contracts

- `AssistantProvider`
- `AssistantRequest`
- `AssistantProviderResponse`
- `ProviderCapabilities`
- `ProviderHealth`
- `ProviderError`
- `ProviderUnavailableError`
- `ProviderTimeoutError`
- `ProviderSafetyError`

## Implementations

- `DeterministicAssistantProvider`: no network, rule-based fallback provider.
- `OpenAICompatibleAssistantProvider`: minimal HTTP provider using Python standard library and injectable transport.

## Safety

Provider output is rejected when it is empty, too long, or claims forbidden actions such as order execution, automatic approval, or policy application. Provider failures produce `fallback` responses and do not stop Telegram runtime.

## Prompt Boundary

`prompt_builder.py` separates system instructions, user text, and retrieved memory data. User text and retrieved context are treated as untrusted data, not instructions.

Sprint 15 does not add external SDK dependencies or real API-call tests.
