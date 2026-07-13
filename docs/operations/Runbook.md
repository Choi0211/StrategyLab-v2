# StrategyLab v2 Runbook

## Test

```bash
PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit
```

## Release Verification

```bash
python scripts/verify_release.py
```

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
git push origin develop-v2
```

