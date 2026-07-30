# Incident Response

Status: Sprint 17 operations guide

## First Checks

- `python -m gaon.runtime.cli config-check`
- `python -m gaon.runtime.cli deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon`
- `python -m gaon.runtime.cli health --db <runtime.sqlite>`
- `python -m gaon.runtime.cli readiness --db <runtime.sqlite>`
- systemd status and journal logs

If production behavior does not match the reviewed source, check whether Gaon
is being imported from `.venv/lib/python*/site-packages` instead of
`/opt/strategylab-v2/src/gaon`. Reinstall with `.venv/bin/pip install -e .`
and restart `strategylab-gaon` before continuing diagnosis.

## Rules

- Mask tokens and API keys.
- Do not paste full user payloads into public issues.
- Stop service before restoring runtime SQLite.
- Prefer rollback to the last reviewed tag.
- Do not connect or modify private trading systems from this repository.
