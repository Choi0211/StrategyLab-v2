# Incident Response

Status: Sprint 17 operations guide

## First Checks

- `python -m gaon.runtime.cli config-check`
- `python -m gaon.runtime.cli health --db <runtime.sqlite>`
- `python -m gaon.runtime.cli readiness --db <runtime.sqlite>`
- systemd status and journal logs

## Rules

- Mask tokens and API keys.
- Do not paste full user payloads into public issues.
- Stop service before restoring runtime SQLite.
- Prefer rollback to the last reviewed tag.
- Do not connect or modify private trading systems from this repository.
