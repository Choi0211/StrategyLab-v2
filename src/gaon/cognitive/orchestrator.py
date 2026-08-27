"""Bounded cognitive coordination over existing Gaon stores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from hashlib import sha256

from gaon.cognitive.models import CognitiveRecord, CognitiveRecordType, GoalStatus, RetrievedCognitiveContext
from gaon.cognitive.repository import SQLiteCognitiveRepository
from gaon.learning.long_term_memory import (
    MemoryLifecycle,
    MemoryNamespace,
    MemoryRecord,
    SQLiteLongTermMemoryRepository,
)


class CognitiveOrchestrator:
    """Coordinates memory and goals without becoming a second research brain."""

    def __init__(self, connection: sqlite3.Connection, *, max_context_items: int = 8) -> None:
        self.records = SQLiteCognitiveRepository(connection)
        self.connection = connection
        self.memories = SQLiteLongTermMemoryRepository(connection)
        self.max_context_items = max(1, min(max_context_items, 20))

    def observe_user_message(
        self, *, namespace: str, message: str, source_ref: str, now: str
    ) -> tuple[str, ...]:
        actions: list[str] = []
        if _is_repetition_feedback(message):
            memory_id = f"cognitive-preference:{_digest(namespace + ':avoid_repetitive_status')}"
            try:
                self.memories.get(memory_id)
            except KeyError:
                proposed = MemoryRecord.propose(
                    memory_id,
                    MemoryNamespace.CONVERSATION,
                    json.dumps({
                        "category": "conversation_preference",
                        "preference": "avoid_repetitive_status",
                        "namespace": namespace,
                    }, ensure_ascii=False, sort_keys=True),
                    source_refs=(source_ref,),
                    evidence_refs=(source_ref,),
                    created_at=now,
                )
                self.memories.add(proposed)
                self.memories.update(proposed.validate(
                    validation_ref=source_ref, trusted_workflow=True, updated_at=now
                ))
            actions.append("preference:avoid_repetitive_status")
            self._record_reflection(
                namespace=namespace,
                message=message,
                source_ref=source_ref,
                now=now,
                suspected_cause="response repetition reduced usefulness",
            )
            actions.append("reflection:repeated_response")
        return tuple(actions)

    def create_goal(
        self,
        *,
        namespace: str,
        title: str,
        description: str,
        reason: str,
        success_criteria: tuple[str, ...],
        next_action: str,
        source_ref: str,
        now: str,
        parent_goal_id: str | None = None,
    ) -> CognitiveRecord:
        identity = _digest(namespace + ":" + title.casefold())
        try:
            existing = self.records.get(f"cognitive-goal:{identity}")
        except KeyError:
            existing = None
        if existing is not None:
            return existing
        record = CognitiveRecord(
            record_id=f"cognitive-goal:{identity}",
            record_type=CognitiveRecordType.GOAL,
            namespace=namespace,
            title=title,
            status=GoalStatus.ACTIVE.value,
            payload={
                "description": description,
                "reason": reason,
                "priority": "normal",
                "success_criteria": list(success_criteria),
                "next_action": next_action,
                "blockers": [],
                "attempts": [],
                "parent_goal_id": parent_goal_id,
                "completed_at": None,
            },
            source_refs=(source_ref,),
            evidence_refs=(source_ref,),
            confidence=1.0,
            verification_state="user_directed",
            related_goal=parent_goal_id,
            created_at=now,
            updated_at=now,
        )
        self.records.put(record)
        return record

    def record_knowledge_gap(
        self,
        *,
        namespace: str,
        question: str,
        why_needed: str,
        related_goal: str,
        suggested_sources: tuple[str, ...],
        source_ref: str,
        now: str,
    ) -> CognitiveRecord:
        goal = self.records.get(related_goal)
        if goal.namespace != namespace or goal.record_type is not CognitiveRecordType.GOAL:
            raise ValueError("knowledge gap requires a goal in the same namespace")
        record = CognitiveRecord(
            record_id=f"knowledge-gap:{_digest(namespace + ':' + question.casefold())}",
            record_type=CognitiveRecordType.KNOWLEDGE_GAP,
            namespace=namespace,
            title=question,
            status="open",
            payload={
                "question": question,
                "why_needed": why_needed,
                "urgency": "normal",
                "current_confidence": 0.0,
                "suggested_sources": list(suggested_sources),
                "resolved_at": None,
            },
            source_refs=(source_ref,),
            evidence_refs=(),
            confidence=0.0,
            verification_state="gap",
            related_goal=related_goal,
            created_at=now,
            updated_at=now,
        )
        self.records.put(record)
        return record

    def register_tool(
        self, *, namespace: str, tool_id: str, name: str, purpose: str,
        domain: str, location: str, version: str, capabilities: tuple[str, ...],
        limitations: tuple[str, ...], risk_level: str, test_status: str, now: str,
    ) -> CognitiveRecord:
        record = CognitiveRecord(
            record_id=f"tool:{_digest(namespace + ':' + tool_id)}",
            record_type=CognitiveRecordType.TOOL,
            namespace=namespace,
            title=name,
            status="available" if test_status == "pass" else "restricted",
            payload={"purpose": purpose, "domain": domain, "location": location,
                     "version": version, "capabilities": list(capabilities),
                     "limitations": list(limitations), "risk_level": risk_level,
                     "test_status": test_status, "last_evaluated_at": now},
            source_refs=(location,), evidence_refs=(),
            confidence=1.0 if test_status == "pass" else 0.5,
            verification_state="declared_capability",
            related_goal=None, created_at=now, updated_at=now,
        )
        self.records.put(record)
        return record

    def retrieve(self, *, namespace: str, query: str) -> RetrievedCognitiveContext:
        preferences: list[str] = []
        try:
            preference_records = (self.memories.get(
                f"cognitive-preference:{_digest(namespace + ':avoid_repetitive_status')}"
            ),)
        except KeyError:
            preference_records = ()
        for memory in preference_records:
            if memory.lifecycle is not MemoryLifecycle.VALIDATED:
                continue
            try:
                payload = json.loads(memory.content)
            except json.JSONDecodeError:
                continue
            if payload.get("namespace") == namespace and payload.get("category") == "conversation_preference":
                preferences.append(str(payload.get("preference")))
        relevant = any(word in query.casefold() for word in (
            "연구", "전략", "계속", "아까", "그거", "목표", "진행", "reflection", "research", "continue", "goal"
        ))
        goals = self.records.list(
            namespace=namespace,
            record_type=CognitiveRecordType.GOAL,
            statuses=(GoalStatus.ACTIVE.value, GoalStatus.BLOCKED.value),
            limit=max(0, self.max_context_items - len(preferences)) if relevant else 0,
        )
        remaining = max(0, self.max_context_items - len(goals) - len(preferences))
        reflections = self.records.list(
            namespace=namespace, record_type=CognitiveRecordType.REFLECTION,
            limit=remaining if _is_repetition_feedback(query) else 0,
        )
        remaining = max(0, remaining - len(reflections))
        gaps = self.records.list(
            namespace=namespace,
            record_type=CognitiveRecordType.KNOWLEDGE_GAP,
            statuses=("open",),
            limit=remaining if relevant else 0,
        )
        remaining = max(0, remaining - len(gaps))
        projects = self.records.list(namespace=namespace, record_type=CognitiveRecordType.PROJECT,
                                     limit=remaining if relevant else 0)
        return RetrievedCognitiveContext(
            preferences=tuple(preferences[: self.max_context_items]),
            active_goals=goals,
            reflections=reflections,
            knowledge_gaps=gaps,
            projects=projects,
            research_refs=tuple(ref for goal in goals for ref in goal.source_refs),
            budget_used=min(self.max_context_items, len(preferences) + len(goals) + len(reflections) + len(gaps) + len(projects)),
        )

    def transition_goal(self, goal_id: str, *, namespace: str, status: GoalStatus, now: str) -> CognitiveRecord:
        goal = self.records.get(goal_id)
        if goal.namespace != namespace or goal.record_type is not CognitiveRecordType.GOAL:
            raise ValueError("goal scope mismatch")
        payload = dict(goal.payload)
        payload["completed_at"] = now if status is GoalStatus.COMPLETED else None
        updated = replace(goal, status=status.value, payload=payload, updated_at=now)
        self.records.put(updated)
        return updated

    def propose_learning(self, *, namespace: str, topic: str, content: str,
                         source_ref: str, now: str, input_type: str = "text") -> MemoryRecord:
        if input_type not in {"text", "url", "document", "image_result", "research_result", "user_explanation"}:
            raise ValueError("unsupported learning input")
        if not content.strip() or len(content) > 12000 or not source_ref:
            raise ValueError("bounded content and provenance required")
        prefix = f"cognitive-learning:{_digest(namespace + ':' + topic)}:"
        identity = prefix + _digest(content)
        try:
            return self.memories.get(identity)
        except KeyError:
            pass
        # The source attests acquisition, not truth. Only the existing trusted
        # knowledge workflow can validate these proposed records.
        record = MemoryRecord.propose(identity, MemoryNamespace.LEARNING,
            json.dumps({"namespace": namespace, "topic": topic, "content": content,
                        "input_type": input_type}, ensure_ascii=False, sort_keys=True),
            source_refs=(source_ref,), evidence_refs=(source_ref,), created_at=now)
        rows = self.connection.execute(
            "SELECT memory_id, content FROM long_term_memory WHERE namespace=? AND memory_id LIKE ? LIMIT 100",
            (MemoryNamespace.LEARNING.value, prefix + "%"),
        ).fetchall()
        for memory_id, raw in rows:
            previous = json.loads(raw)
            if previous.get("namespace") == namespace and previous.get("topic") == topic and previous.get("content") != content:
                prior = self.memories.get(str(memory_id)).mark_conflict(updated_at=now)
                self.memories.update(prior)
                record = record.mark_conflict(updated_at=now)
        self.memories.add(record)
        return record

    def operational_self_model(self, *, namespace: str, now: str) -> CognitiveRecord:
        """Derive operational claims only from scoped persisted observations."""
        goals = self.records.list(namespace=namespace, record_type=CognitiveRecordType.GOAL, limit=20)
        tools = self.records.list(namespace=namespace, record_type=CognitiveRecordType.TOOL, limit=20)
        reflections = self.records.list(namespace=namespace, record_type=CognitiveRecordType.REFLECTION, limit=20)
        gaps = self.records.list(namespace=namespace, record_type=CognitiveRecordType.KNOWLEDGE_GAP,
                                 statuses=("open",), limit=20)
        record = CognitiveRecord(
            f"self-model:{_digest(namespace)}", CognitiveRecordType.SELF_MODEL, namespace,
            "Operational self model", "observed",
            {"known_capabilities": [t.title for t in tools if t.status == "available"],
             "limitations": ["no autonomous deployment or trading", "proposals require evidence validation"],
             "recurring_failures": [r.title for r in reflections],
             "current_blockers": [g.record_id for g in goals if g.status == GoalStatus.BLOCKED.value],
             "active_learning_needs": [g.record_id for g in gaps],
             "recent_improvements": [],
             "known_tool_capabilities": [t.record_id for t in tools]},
            tuple(r.record_id for r in (*goals, *tools, *reflections, *gaps)), (),
            1.0, "derived_operational_state", None, now, now,
        )
        self.records.put(record)
        return record

    def plan_goal(self, goal_id: str, *, namespace: str, now: str):
        from gaon.runtime.agent_planner import AgentPlanner, AgentPlanPolicy
        goal = self.records.get(goal_id)
        if goal.namespace != namespace or goal.status != GoalStatus.ACTIVE.value:
            raise ValueError("only an active scoped goal can be planned")
        plan = AgentPlanner().plan(str(goal.payload["next_action"]), created_at=now)
        return plan.with_status(AgentPlanPolicy().validate(plan))

    def project(self, *, namespace: str, domain: str, title: str, source_ref: str, now: str) -> CognitiveRecord:
        identity = f"project:{_digest(namespace + ':' + domain + ':' + title.casefold())}"
        try:
            return self.records.get(identity)
        except KeyError:
            record = CognitiveRecord(identity, CognitiveRecordType.PROJECT, namespace,
                title, "active", {"domain": domain, "destructive_action_allowed": False},
                (source_ref,), (), 1.0, "user_directed", None, now, now)
            self.records.put(record)
            return record

    def render_with_preferences(self, *, namespace: str, query: str, text: str, now: str) -> str:
        context = self.retrieve(namespace=namespace, query=query)
        if "avoid_repetitive_status" not in context.preferences or not any(
            word in query for word in ("진행", "상태", "status")
        ):
            return text
        identity = f"cognitive-status:{_digest(namespace)}"
        digest = _digest(text)
        try:
            previous = self.records.get(identity)
        except KeyError:
            previous = None
        record = CognitiveRecord(identity, CognitiveRecordType.SELF_MODEL, namespace,
            "Last rendered status", "observed", {"response_digest": digest}, (), (),
            1.0, "observed", None, now, now)
        self.records.put(record)
        if previous and previous.payload.get("response_digest") == digest:
            return "이전 확인과 비교해 보고할 상태 변경은 없습니다. 같은 상세 설명은 반복하지 않겠습니다."
        return text

    def _record_reflection(
        self, *, namespace: str, message: str, source_ref: str, now: str, suspected_cause: str
    ) -> None:
        record = CognitiveRecord(
            record_id=f"reflection:{_digest(namespace + ':' + source_ref)}",
            record_type=CognitiveRecordType.REFLECTION,
            namespace=namespace,
            title="Repeated response complaint",
            status="open",
            payload={
                "observation": message,
                "expected_result": "concise response focused on material changes",
                "actual_result": "user reported repetition",
                "success": False,
                "suspected_causes": [suspected_cause],
                "lessons": ["retrieve durable conversation preference before rendering"],
                "proposed_improvements": ["avoid repeating unchanged status"],
                "followup_goal": None,
            },
            source_refs=(source_ref,), evidence_refs=(source_ref,), confidence=1.0,
            verification_state="user_reported", related_goal=None,
            created_at=now, updated_at=now,
        )
        self.records.put(record)
        # One durable proposal per recurring issue: repetition does not spawn
        # unbounded autonomous goals or execute changes.
        proposal = replace(record,
            record_id=f"improvement:{_digest(namespace + ':repeated_response')}",
            record_type=CognitiveRecordType.PROACTIVE_IMPROVEMENT,
            status="proposed", title="Avoid repetitive status responses")
        try:
            self.records.get(proposal.record_id)
        except KeyError:
            self.records.put(proposal)


def _is_repetition_feedback(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    return (any(token in normalized for token in ("반복하지 마", "반복했어", "stop repeating", "don't repeat"))
            or (any(token in normalized for token in ("같은 말", "같은 상태", "같은 연구 상태"))
                and any(token in normalized for token in ("왜", "반복하지", "그만", "계속"))))


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:20]
