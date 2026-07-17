# ADR-0006: Runtime Event Bus

Status: Accepted  
Sprint: Runtime Collaboration

Use an in-process deterministic event bus for this phase.

The bus rejects duplicate event IDs and isolates subscriber failures by emitting runtime error events. No external broker is introduced.
