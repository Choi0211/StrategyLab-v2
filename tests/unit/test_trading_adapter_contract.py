import unittest

from gaon.adapters import CommandStatus, FakeTradingAdapter, OrderCommand, RiskGate


class TradingAdapterContractTest(unittest.TestCase):
    def command(self) -> OrderCommand:
        return OrderCommand(
            command_id="cmd-1",
            symbol="005930",
            side="buy",
            quantity=1,
            limit_price=70000,
            status=CommandStatus.PROPOSED,
            proposed_by="youngha",
            created_at="2026-07-17T00:00:00Z",
        )

    def test_read_only_status_methods(self) -> None:
        adapter = FakeTradingAdapter()

        self.assertEqual(adapter.account_summary().currency, "KRW")
        self.assertEqual(adapter.positions(), ())
        self.assertTrue(adapter.market_status("KRX").is_open)
        self.assertEqual(adapter.runtime_status("ORB").mode, "paper")

    def test_order_lifecycle_requires_approval_and_execution_gate(self) -> None:
        adapter = FakeTradingAdapter()
        command = adapter.propose_order(self.command())
        gate = RiskGate(max_holdings=5, max_order_value=100000, daily_loss_limit=50000)

        self.assertTrue(adapter.validate_order(command, gate).passed)
        approved = adapter.approve_order(command, approval_ref="approval-1")
        with self.assertRaises(PermissionError):
            adapter.execute_order(approved)

        enabled = FakeTradingAdapter(execution_enabled=True)
        enabled.propose_order(command)
        executed = enabled.execute_order(enabled.approve_order(command, approval_ref="approval-1"))
        self.assertEqual(executed.status, CommandStatus.EXECUTED)

    def test_risk_gate_rejects_closed_market_and_large_order(self) -> None:
        adapter = FakeTradingAdapter(market_open=False)
        command = self.command()
        result = adapter.validate_order(command, RiskGate(max_holdings=5, max_order_value=100, daily_loss_limit=50000))

        self.assertFalse(result.passed)
        self.assertIn("max order value exceeded", result.reasons)
        self.assertIn("market is closed", result.reasons)

    def test_cancel_order(self) -> None:
        adapter = FakeTradingAdapter()
        cancelled = adapter.cancel_order(self.command(), reason="user cancelled")

        self.assertEqual(cancelled.status, CommandStatus.CANCELLED)
        self.assertEqual(cancelled.rejection_reason, "user cancelled")


if __name__ == "__main__":
    unittest.main()
