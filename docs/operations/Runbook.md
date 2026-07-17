# StrategyLab v2 Runbook

## Test

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src;tests/unit;tests/integration"
py -3.11 -m unittest discover -s tests/unit
py -3.11 -m unittest discover -s tests/integration
```

Linux/macOS bash:

```bash
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/unit
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/integration
```

## Release Verification

Windows PowerShell:

```powershell
py -3.11 scripts/verify_release.py
```

Linux/macOS bash:

```bash
python3.11 scripts/verify_release.py
```

## Phase A Diagnostics

```powershell
py -3.11 -m gaon.runtime.cli config-check
py -3.11 -m gaon.runtime.cli health
py -3.11 -m gaon.runtime.cli db-check
py -3.11 -m gaon.runtime.cli status
py -3.11 -m gaon.runtime.cli metrics
py -3.11 -m gaon.runtime.cli event-replay-dry-run
```

Expected runtime DB schema version: `5`.

## Safety

Do not add:

- `.env`
- broker tokens
- account files
- private market data dumps
- production logs
- MyMoneyGuard private files

## Git Push

```bash
git push origin feature/gaon-phase-a-v2.1
```
