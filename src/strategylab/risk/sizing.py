"""Risk-based sizing helpers."""

from __future__ import annotations


def atr_position_size(capital: float, risk_fraction: float, atr: float, atr_multiple: float) -> int:
    if capital <= 0:
        raise ValueError("capital must be positive")
    if not 0 < risk_fraction <= 1:
        raise ValueError("risk_fraction must be in (0, 1]")
    if atr <= 0:
        raise ValueError("atr must be positive")
    if atr_multiple <= 0:
        raise ValueError("atr_multiple must be positive")
    risk_budget = capital * risk_fraction
    per_share_risk = atr * atr_multiple
    return int(risk_budget // per_share_risk)

