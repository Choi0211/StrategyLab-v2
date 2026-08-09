from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_learning_e2e import autonomous_learning_e2e_release_check
from gaon.knowledge.telegram_autonomous_learning import telegram_autonomous_learning_payload
from gaon.runtime.storage import RuntimeStateStore


class AutonomousLearningE2EReleaseCheckTests(unittest.TestCase):
    def test_release_check_reaches_human_approval_required(self) -> None:
        payload = autonomous_learning_e2e_release_check()

        self.assertEqual("proposed", payload["hypothesis_status"])
        self.assertEqual("accepted_for_review", payload["validation_status"])
        self.assertEqual("ranked", payload["ranking_status"])
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
        self.assertEqual("pass", payload["safety"])

    def test_telegram_wrapper_preserves_approval_boundary(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            payload = telegram_autonomous_learning_payload(
                store._connection,
                "삼성전자 전략을 처음부터 다시 연구해줘",
                symbol="005930",
            )

            self.assertEqual("autonomous_learning_research", payload["tool"])
            self.assertEqual("005930", payload["symbol"])
            self.assertEqual("autonomous_learning_v2", payload["selected_orchestration"])
            self.assertEqual("requires_human_approval", payload["promotion_status"])
            self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])
            self.assertFalse(payload["broker_order_called"])
            self.assertFalse(payload["kis_order_called"])
            self.assertIn("baseline", payload)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
