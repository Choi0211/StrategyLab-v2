# ADR-0010: Plugin Lifecycle Security

Status: Accepted

Gaon plugins must be explicitly registered allowlist objects.

Consequences:

- no arbitrary directory scanning
- no untrusted importlib loading
- disabled plugins do not start
- one plugin failure is isolated
- plugins cannot run DB migrations directly
- plugins cannot bypass approvals
