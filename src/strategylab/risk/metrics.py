"""Risk metrics."""

from __future__ import annotations

from strategylab.risk.models import CircuitBreakerDecision, EmergencyStopDecision, RiskScore


def max_drawdown(equity_curve: tuple[float, ...]) -> float:
    if not equity_curve:
        raise ValueError("equity_curve is required")
    peak = equity_curve[0]
    worst = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = 0.0 if peak == 0 else (equity - peak) / peak
        worst = min(worst, drawdown)
    return round(worst, 6)


def portfolio_exposure(holdings_value: float, total_equity: float) -> float:
    if total_equity <= 0:
        raise ValueError("total_equity must be positive")
    return round(holdings_value / total_equity, 6)


def risk_score(drawdown: float, exposure: float) -> RiskScore:
    normalized_drawdown = min(abs(drawdown), 1.0)
    normalized_exposure = min(max(exposure, 0.0), 1.0)
    score = round((normalized_drawdown + normalized_exposure) / 2.0, 6)
    return RiskScore(score=score, reason=f"drawdown={drawdown}, exposure={exposure}")


def emergency_stop(drawdown: float, limit: float) -> EmergencyStopDecision:
    triggered = drawdown <= -abs(limit)
    return EmergencyStopDecision(triggered, f"drawdown={drawdown}, limit={limit}")


def circuit_breaker(daily_loss: float, limit: float) -> CircuitBreakerDecision:
    triggered = daily_loss <= -abs(limit)
    return CircuitBreakerDecision(triggered, f"daily_loss={daily_loss}, limit={limit}")

