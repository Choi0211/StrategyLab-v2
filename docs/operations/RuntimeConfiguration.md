# Runtime Configuration

Gaon Runtime uses environment variables and defaults to dry-run.

See `.env.example` for the complete list.

Secrets must not be committed. Runtime repr masks token values.

Required execute-mode conditions:

- integration enabled explicitly
- token provided through environment
- dry-run disabled explicitly
- execute mode selected explicitly

Tests do not require real tokens.
