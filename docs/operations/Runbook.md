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

## VPS Deployment Verification

Production deployments must refresh the editable package and verify the module
path before restarting the long-running service:

```bash
cd /opt/strategylab-v2
git pull origin main
.venv/bin/pip install -e .
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
sudo systemctl restart strategylab-gaon
sudo systemctl status strategylab-gaon
```

The import-path check must show `actual=/opt/strategylab-v2/src/gaon`. A
`.venv/lib/python*/site-packages/gaon` path means the VPS is running a stale
copied package and the service must not be treated as upgraded.

For Autonomous Learning V2 production-loop verification, run:

```bash
.venv/bin/python -m gaon.runtime.cli gaon-production-relevant-academic-discovery-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-safe-doi-redirect-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-relevant-academic-content-loop-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-real-academic-content-resolution-release-check
.venv/bin/python -m gaon.runtime.cli gaon-production-autonomous-learning-loop-release-check
```

These checks verify strategy-specific academic relevance screening, rejection
of irrelevant non-financial papers, DOI redirect safety, academic DOI/resource
resolution, content-grounded evidence, evidence-backed hypotheses, candidate
experiment lineage, authoritative real candidate validation, robustness
ranking, and the human-only promotion gate without mutating strategy
configuration or placing orders.

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
