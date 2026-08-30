import unittest
from gaon.cognitive.release_check import cognitive_release_check
from gaon.cognitive.presentation import binance_snapshot_reply
from gaon.cognitive.orchestrator import CognitiveOrchestrator
from gaon.runtime.storage import RuntimeStateStore


class CognitiveCoreTests(unittest.TestCase):
    def test_v36_upgrade_is_additive_and_idempotent(self):
        import sqlite3
        from unittest.mock import patch
        from gaon.runtime import migrations
        connection = sqlite3.connect(":memory:")
        try:
            with patch.object(migrations, "SCHEMA_VERSION", 36):
                migrations.migrate(connection)
            connection.execute("INSERT INTO conversation_sessions VALUES (?,?,?,?,?,?,?)",
                               ("existing", "user", "web", "active", "now", "now", "{}"))
            connection.commit()
            migrations.migrate(connection)
            migrations.migrate(connection)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM conversation_sessions WHERE session_id='existing'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_version WHERE version=40").fetchone()[0], 1)
        finally:
            connection.close()

    def test_operational_self_model_and_proactive_deduplication(self):
        from gaon.cognitive.models import CognitiveRecordType
        store = RuntimeStateStore(":memory:")
        try:
            core = CognitiveOrchestrator(store._connection)
            for index in range(3):
                core.observe_user_message(namespace="A", message="왜 같은 말을 반복했어?",
                                          source_ref=f"user:{index}", now="2026-08-27T00:00:00Z")
            self.assertEqual(len(core.records.list(namespace="A", record_type=CognitiveRecordType.PROACTIVE_IMPROVEMENT)), 1)
            model = core.operational_self_model(namespace="A", now="2026-08-27T00:00:00Z")
            self.assertEqual(len(model.payload["recurring_failures"]), 3)
            self.assertEqual(model.payload["recent_improvements"], [])
            self.assertEqual(core.operational_self_model(namespace="B", now="2026-08-27").payload["recurring_failures"], [])
        finally:
            store.close()

    def test_durable_acceptance(self):
        self.assertEqual(cognitive_release_check()["status"], "pass")

    def test_client_snapshot_is_not_verified_market_evidence(self):
        context = {"domain": "binance", "source": "dashboard_state_snapshot", "equity": 5.72,
                   "positions": [{"symbol": "BTCUSDT", "amount": -0.1}]}
        self.assertIsNone(binance_snapshot_reply("안녕", context))
        text = binance_snapshot_reply("현재 Binance 포지션 알려줘", context)
        self.assertIn("실시간 재조회 결과는 아닙니다", text)
        self.assertIn("BTCUSDT", text)

    def test_proposals_never_execute_and_goal_scope_checked(self):
        store = RuntimeStateStore(":memory:")
        try:
            core = CognitiveOrchestrator(store._connection)
            goal = core.create_goal(namespace="A", title="review", description="review", reason="user",
                success_criteria=("review",), next_action="deploy production", source_ref="user:1", now="2026-08-27")
            self.assertEqual(core.plan_goal(goal.record_id, namespace="A", now="2026-08-27").status.value, "requires_human_approval")
            with self.assertRaises(ValueError):
                core.plan_goal(goal.record_id, namespace="B", now="2026-08-27")
            first = core.project(namespace="A", domain="software_development", title="Gaon", source_ref="user:1", now="2026-08-27")
            self.assertEqual(first.record_id, core.project(namespace="A", domain="software_development", title="Gaon", source_ref="user:2", now="2026-08-27").record_id)
        finally:
            store.close()
