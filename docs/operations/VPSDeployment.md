# VPS Deployment

Status: Sprint 21 controlled runtime loop guide

This repository does not execute deployment automatically.

## Requirements

- non-root `strategylab` user
- `/opt/strategylab-v2` working directory
- `/etc/strategylab/gaon.env` outside Git
- systemd service installed from `deploy/systemd/strategylab-gaon.service`

## Commands

```bash
python -m gaon.runtime.cli config-check
python -m gaon.runtime.cli db-check --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli health --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli run --db /opt/strategylab-v2/runtime.sqlite
python -m gaon.runtime.cli status --db /opt/strategylab-v2/runtime.sqlite
sudo systemctl daemon-reload
sudo systemctl enable strategylab-gaon.service
sudo systemctl start strategylab-gaon.service
sudo systemctl status strategylab-gaon.service
```

`run` starts the controlled runtime service path and performs a deterministic tick in this public repository phase. External Telegram, OpenAI, Notion, and broker loops are not claimed as live-verified here.

## Safety

Do not place secrets in Git. Do not run as root. Do not connect private trading systems from this public repository.

## v5 Safe Upgrade Procedure

1. Pull latest `main` into the source working copy.
2. Refresh the editable installation with `.venv/bin/pip install -e .`.
3. Verify the imported module path with `.venv/bin/python -m gaon.runtime.cli deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon`.
4. Run unit tests, integration tests, and `.venv/bin/python scripts/verify_release.py`.
5. Back up the runtime SQLite DB.
6. Check the environment file outside Git.
7. Run `.venv/bin/python -m gaon.runtime.cli db-check --db /var/lib/strategylab/gaon-runtime.sqlite`.
8. Restart `strategylab-gaon.service`.
9. Run health, Telegram check, import-path check, and `v5-status`.
10. If the upgrade fails, stop the service, restore the DB backup, restore the previous code version, reinstall editable mode, and restart.

## Editable Install Requirement

Production must execute Gaon from the reviewed source tree, not from a stale
copied package under `.venv/lib/python*/site-packages`. Every VPS deployment
therefore requires:

```bash
cd /opt/strategylab-v2
git pull origin main
.venv/bin/pip install -e .
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
.venv/bin/python -m gaon.runtime.cli gaon-production-gaon-v2-completion-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite
.venv/bin/python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite
sudo systemctl restart strategylab-gaon
sudo systemctl status strategylab-gaon
```

Expected import-path output:

```text
deployment-import-path-check: PASS actual=/opt/strategylab-v2/src/gaon expected=/opt/strategylab-v2/src/gaon editable_source=true
```

If the command reports `site-packages` or any path outside
`/opt/strategylab-v2/src/gaon`, stop the service, reinstall with
`.venv/bin/pip install -e .`, and restart before running production Telegram or
market-data verification.

The public repository documents the adapter contract only. A real v1 production
deployment adapter must provide health check, active strategy discovery,
package validation, backup, dry-run, apply, restart/reload, verification,
rollback, and status reporting.
