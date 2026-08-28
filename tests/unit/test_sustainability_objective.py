"""Hotfix #166: durable Sustainability & Growth objective.

Proves the objective is real Cognitive Core durable state (not a system
prompt string), survives restart, never collides with or leaks into any
per-user/session namespace, and carries an explicit, structured list of
forbidden justifications that must never expand to authorize risk/
leverage/approval-bypass/promotion/order-execution.
"""

from __future__ import annotations

import unittest

from gaon.cognitive.models import CognitiveRecordType
from gaon.cognitive.orchestrator import CognitiveOrchestrator
from gaon.cognitive.sustainability import (
    FORBIDDEN_JUSTIFICATIONS,
    SUSTAINABILITY_DIMENSIONS,
    SUSTAINABILITY_NAMESPACE,
    ensure_sustainability_objective,
    is_forbidden_justification,
    sustainability_objective,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation_context import ConversationContextOrchestrator
from gaon.runtime.llm_conversation import LLMConversationBrain, SQLiteConversationRepository
from gaon.runtime.storage import RuntimeStateStore

_NOW = "2026-08-29T00:00:00Z"


class SustainabilityObjectiveTests(unittest.TestCase):
    def test_sustainability_objective_is_none_before_bootstrap(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        self.assertIsNone(sustainability_objective(store._connection))

    def test_ensure_creates_a_durable_record_with_structured_forbidden_list(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        record = ensure_sustainability_objective(store._connection, now=_NOW)

        self.assertEqual(record.record_type, CognitiveRecordType.GOAL)
        self.assertEqual(record.namespace, SUSTAINABILITY_NAMESPACE)
        self.assertEqual(record.status, "active")
        self.assertEqual(tuple(record.payload["forbidden_justifications"]), FORBIDDEN_JUSTIFICATIONS)
        self.assertEqual(tuple(record.payload["sustainability_dimensions"]), SUSTAINABILITY_DIMENSIONS)
        for forbidden in ("risk_increase", "leverage_increase", "approval_bypass", "champion_auto_promotion", "strategy_auto_apply", "live_order_execution", "fabricated_evidence"):
            self.assertIn(forbidden, record.payload["forbidden_justifications"])

    def test_ensure_is_idempotent_and_does_not_bump_updated_at(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        first = ensure_sustainability_objective(store._connection, now=_NOW)
        second = ensure_sustainability_objective(store._connection, now="2026-09-01T00:00:00Z")

        self.assertEqual(first.record_id, second.record_id)
        self.assertEqual(second.updated_at, _NOW, "a second ensure call must not refresh an already-persisted objective")

    def test_survives_restart(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "gaon.sqlite3")
            store = RuntimeStateStore(db_path)
            created = ensure_sustainability_objective(store._connection, now=_NOW)
            store.close()

            reopened = RuntimeStateStore(db_path)
            try:
                restored = sustainability_objective(reopened._connection)
            finally:
                reopened.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.record_id, created.record_id)
        self.assertEqual(tuple(restored.payload["forbidden_justifications"]), FORBIDDEN_JUSTIFICATIONS)

    def test_never_visible_in_any_user_or_session_namespace_retrieval(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        ensure_sustainability_objective(store._connection, now=_NOW)
        core = CognitiveOrchestrator(store._connection)

        for namespace in ("web:some-session", "web-user:someone", "telegram:100"):
            context = core.retrieve(namespace=namespace, query="anything")
            self.assertEqual(context.active_goals, (), f"sustainability objective leaked into namespace {namespace!r}")

    def test_creating_a_real_user_goal_never_collides_with_the_system_namespace(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        ensure_sustainability_objective(store._connection, now=_NOW)
        core = CognitiveOrchestrator(store._connection)

        core.create_goal(
            namespace="web:some-session",
            title="사용자 목표",
            description="사용자 개인 목표",
            reason="user request",
            success_criteria=(),
            next_action="계속 진행",
            source_ref="test",
            now=_NOW,
        )

        system_context = core.retrieve(namespace=SUSTAINABILITY_NAMESPACE, query="anything")
        self.assertEqual(system_context.active_goals, (), "system namespace must not be reachable/polluted by ordinary user goal creation")
        # and the system objective itself is untouched
        objective = sustainability_objective(store._connection)
        self.assertIsNotNone(objective)

    def test_llm_conversation_brain_construction_auto_bootstraps_the_objective(self) -> None:
        store = RuntimeStateStore(":memory:")
        self.addCleanup(store.close)
        repository = SQLiteConversationRepository(store._connection)
        LLMConversationBrain(
            GaonRuntimeConfig(),
            repository,
            context_orchestrator=ConversationContextOrchestrator(store._connection, repository),
        )

        objective = sustainability_objective(store._connection)
        self.assertIsNotNone(objective)
        self.assertEqual(objective.namespace, SUSTAINABILITY_NAMESPACE)

    def test_is_forbidden_justification_helper(self) -> None:
        self.assertTrue(is_forbidden_justification("leverage_increase"))
        self.assertTrue(is_forbidden_justification("live_order_execution"))
        self.assertFalse(is_forbidden_justification("bounded_new_hypothesis"))


if __name__ == "__main__":
    unittest.main()
