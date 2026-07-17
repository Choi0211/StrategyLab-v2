# ADR-0012: Long-Term Memory Lifecycle

Status: Accepted

Long-term memory extends Learning Memory without replacing it.

All memory enters as `proposed`. Validation requires an explicit trusted workflow. LLM output never becomes validated automatically.

Consequences:

- namespaces separate learning, research, conversation, and system memory
- system memory requires stricter authorization
- conversation memory has retention controls
- prompt injection text remains untrusted data
- no vector DB is introduced
