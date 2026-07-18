# Evidence Pipeline

Status: Phase B Sprint 31

Evidence collection is provider-neutral and bounded.

Providers must implement explicit `SearchProvider` contracts. Tests use fake, local fixture, and RSS/Atom fixture providers only. Optional web search adapters are disabled by default and require explicit configuration.

Safety rules:

- no live network is required for automated tests
- result count is bounded
- content size is bounded
- domains may be allowlisted or denied
- duplicate canonical URLs are removed
- LLMs do not browse directly
