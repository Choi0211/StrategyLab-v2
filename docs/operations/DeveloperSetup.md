# Developer Setup

Status: Sprint 1 Foundation

## Requirements

- Python 3.11 or newer
- No broker credential is required
- No `.env` file is required

## Install

```bash
python -m pip install -e .
```

## Run Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit
```

## Configuration

Use `config/config.example.yaml` for public development. Use `.env.example` only as a placeholder reference. Never commit real secrets.

## Forbidden Files

Do not commit:

- `.env`
- `.env.*` except `.env.example`
- `kis_token.json`
- token files
- account files
- real trade state files
- production logs
