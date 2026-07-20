# External Strategy Research Operations

Sprint 61-70 adds deterministic release checks for external intelligence and autonomous strategy research.

PowerShell:

```powershell
$env:PYTHONPATH='src;tests/unit;tests/integration;tests/fixtures'
python -m gaon.runtime.cli external-research-release-check --db :memory:
python -m gaon.runtime.cli strategy-research-demo --db :memory: --json
```

bash:

```bash
export PYTHONPATH="src:tests/unit:tests/integration:tests/fixtures"
python -m gaon.runtime.cli external-research-release-check --db :memory:
python -m gaon.runtime.cli strategy-research-demo --db :memory: --json
```

Provider configuration:

- Current default provider is `fixture`.
- No external network provider is enabled by default.
- Any future production provider must preserve SSRF blocking, redirect validation, bounded timeout, citation metadata, and untrusted-content handling.

Operational guarantees:

- No secrets are read or logged.
- No live trading or broker order is executed.
- No automatic approval or Champion promotion is performed.
- Research reports are advisory only.
