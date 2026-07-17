# ADR-0009: Assistant Provider Registry

Status: Accepted

Gaon uses explicit provider registration instead of dynamic provider discovery.

Consequences:

- unknown provider configuration fails fast
- duplicate provider names are rejected
- deterministic fallback remains available
- no mandatory external SDK is introduced
- provider routing records fallback reason without prompt or secret leakage
