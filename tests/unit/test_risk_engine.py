import unittest

from strategylab.risk import atr_position_size, max_drawdown, portfolio_exposure, risk_score
from strategylab.risk.metrics import circuit_breaker, emergency_stop


class RiskEngineTest(unittest.TestCase):
    def test_max_drawdown(self) -> None:
        self.assertEqual(max_drawdown((100.0, 120.0, 90.0, 130.0)), -0.25)

    def test_portfolio_exposure(self) -> None:
        self.assertEqual(portfolio_exposure(600.0, 1000.0), 0.6)

    def test_risk_score(self) -> None:
        score = risk_score(drawdown=-0.2, exposure=0.8)
        self.assertEqual(score.score, 0.5)

    def test_emergency_stop(self) -> None:
        decision = emergency_stop(drawdown=-0.12, limit=0.1)
        self.assertTrue(decision.triggered)

    def test_circuit_breaker(self) -> None:
        decision = circuit_breaker(daily_loss=-0.04, limit=0.03)
        self.assertTrue(decision.triggered)

    def test_atr_position_size(self) -> None:
        self.assertEqual(atr_position_size(10000.0, 0.01, 2.0, 2.0), 25)


if __name__ == "__main__":
    unittest.main()

