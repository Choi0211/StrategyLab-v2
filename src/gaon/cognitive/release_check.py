"""Isolated deterministic acceptance: never connects to production services."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import ExitStack


def cognitive_release_check():
    from gaon.cognitive.orchestrator import CognitiveOrchestrator
    from gaon.cognitive.models import CognitiveRecordType
    from gaon.runtime.storage import RuntimeStateStore
    from gaon.runtime.config import GaonRuntimeConfig
    from gaon.runtime.web_api import GaonWebChatAdapter

    with TemporaryDirectory() as directory, ExitStack() as cleanup:
        path = str(Path(directory) / "acceptance.sqlite")
        store = RuntimeStateStore(path)
        cleanup.callback(store.close)
        core = CognitiveOrchestrator(store._connection, max_context_items=2)
        now = "2026-08-27T00:00:00Z"
        core.observe_user_message(namespace="web-user:A", message="같은 연구 상태 설명을 계속 반복하지 마.", source_ref="user:1", now=now)
        goal = core.create_goal(namespace="web:A", title="삼성전자 연구", description="기존 연구 계속",
            reason="user request", success_criteria=("verified research",), next_action="연구 상태 알려줘", source_ref="user:2", now=now)
        core.record_knowledge_gap(namespace="web:A", question="표본이 충분한가?", why_needed="goal validation",
            related_goal=goal.record_id, suggested_sources=("existing research",), source_ref="user:2", now=now)
        first = core.propose_learning(namespace="web:A", topic="sample", content="insufficient",
            source_ref="report:1", now=now)
        duplicate = core.propose_learning(namespace="web:A", topic="sample", content="insufficient", source_ref="report:1", now=now)
        conflict = core.propose_learning(namespace="web:A", topic="sample", content="sufficient", source_ref="report:2", now=now)
        assert first.memory_id == duplicate.memory_id and conflict.conflict_flag
        assert conflict.lifecycle.value == "proposed"
        core.render_with_preferences(namespace="web-user:A", query="진행상황", text="검증 중입니다.", now=now)
        store.close()
        store = RuntimeStateStore(path)
        try:
            core = CognitiveOrchestrator(store._connection, max_context_items=2)
            assert core.records.get(goal.record_id).status == "active"
            assert core.retrieve(namespace="web:B", query="연구").active_goals == ()
            assert core.retrieve(namespace="web-user:B", query="상태").preferences == ()
            assert core.retrieve(namespace="web-user:A", query="상태").preferences == ("avoid_repetitive_status",)
            assert "반복하지" in core.render_with_preferences(namespace="web-user:A", query="진행상황", text="검증 중입니다.", now=now)
            context = core.retrieve(namespace="web:A", query="연구")
            assert len(context.active_goals) + len(context.knowledge_gaps) + len(context.reflections) + len(context.preferences) <= 2
            assert core.records.list(namespace="web:A", limit=0) == ()
            adapter = GaonWebChatAdapter(GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"), store._connection)
            greeting = adapter.handle(message="안녕", session_ref="A", user_ref="A", read_only=False, received_at=now)
            assert greeting["route"] == "conversation_greeting" and not greeting["tool_calls"]
            feedback = adapter.handle(message="왜 같은 말을 반복했어?", session_ref="A", user_ref="A", read_only=False, received_at=now)
            assert feedback["route"] == "cognitive_feedback"
            assert core.records.list(namespace="web-user:A", record_type=CognitiveRecordType.REFLECTION)
            assert not any(greeting[key] for key in ("strategy_mutated", "order_executed", "champion_promoted", "approval_bypassed"))
        finally:
            store.close()
    return {"status": "pass", "restart": True, "feedback_retrieved": True, "session_isolation": True,
            "greeting_isolation": True, "bounded_context": True, "learning_requires_validation": True,
            "order_executed": False, "strategy_mutated": False, "production_auto_deployed": False}
