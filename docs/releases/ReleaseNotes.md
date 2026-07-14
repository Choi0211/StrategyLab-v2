# StrategyLab v2.0 Foundation Release Candidate Notes

Status: Release Candidate Foundation  
Base: StrategyLab v1.0 Stable Release

## Included

- Blueprint and sprint governance.
- Public/private separation policy.
- Core project foundation.
- Market data contracts and validation.
- Strategy parameter and signal framework.
- Deterministic backtest contracts.
- Portfolio accounting foundation.
- Risk metric foundation.
- AI review schema foundation.
- Dashboard view model foundation.
- Safe broker interface and paper adapter.
- End-to-end integration test from market fixture through strategy, portfolio sizing, risk validation, backtest, and paper broker fill.
- GitHub Actions verification on Ubuntu and Windows with Python 3.11 and 3.12.

## Not Included

- Live trading.
- Real broker API credentials.
- Private MyMoneyGuard access.
- Production deployment.
- Full optimizer.

## Verification

Run:

```bash
PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit
PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration
python scripts/verify_release.py
```
