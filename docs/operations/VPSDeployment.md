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
2. Run unit tests, integration tests, and `python scripts/verify_release.py`.
3. Back up the runtime SQLite DB.
4. Sync release code to the production location.
5. Rebuild or refresh the virtual environment if dependencies changed.
6. Check the environment file outside Git.
7. Run `python -m gaon.runtime.cli db-check --db /var/lib/strategylab/gaon-runtime.sqlite`.
8. Restart `strategylab-gaon.service`.
9. Run health, Telegram check, and `v5-status`.
10. If the upgrade fails, stop the service, restore the DB backup, restore the previous code version, and restart.

The public repository documents the adapter contract only. A real v1 production
deployment adapter must provide health check, active strategy discovery,
package validation, backup, dry-run, apply, restart/reload, verification,
rollback, and status reporting.
