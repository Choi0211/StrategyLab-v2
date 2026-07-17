# Research Runtime Operations

Status: dry-run first

Research runtime commands are local smoke commands for planning, deterministic dry-run execution, status inspection, report rendering, and resume checks.

## Commands

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src;tests/unit;tests/integration"
py -3.11 -m gaon.runtime.cli research-plan --query "ORB evidence"
py -3.11 -m gaon.runtime.cli research-run --query "ORB evidence" --dry-run
py -3.11 -m gaon.runtime.cli research-status run-1
py -3.11 -m gaon.runtime.cli research-report run-1 --format markdown
py -3.11 -m gaon.runtime.cli research-resume run-1
```

Linux/macOS bash:

```bash
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m gaon.runtime.cli research-plan --query "ORB evidence"
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m gaon.runtime.cli research-run --query "ORB evidence" --dry-run
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m gaon.runtime.cli research-status run-1
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m gaon.runtime.cli research-report run-1 --format markdown
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m gaon.runtime.cli research-resume run-1
```

## Current Limits

- CLI research run uses deterministic dry-run evidence.
- Status, report, and resume commands are smoke paths unless wired to a persistent runtime database in a future sprint.
- No live market data, live search, paid AI provider, Telegram execution, Notion sync, broker, or MyMoneyGuard integration is required.

## Verification

Run:

```powershell
$env:PYTHONPATH = "src;tests/unit;tests/integration"
py -3.11 -m unittest discover -s tests/unit
py -3.11 -m unittest discover -s tests/integration
py -3.11 scripts/verify_release.py
```
