import unittest


class ImportSmokeTest(unittest.TestCase):
    def test_package_imports(self) -> None:
        import gaon
        import gaon.learning
        import strategylab
        import strategylab.backtest
        import strategylab.broker
        import strategylab.dashboard
        import strategylab.market
        import strategylab.notification
        import strategylab.portfolio
        import strategylab.reports
        import strategylab.research
        import strategylab.risk
        import strategylab.strategies

        self.assertEqual(gaon.__version__, "0.1.0")
        self.assertEqual(strategylab.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
