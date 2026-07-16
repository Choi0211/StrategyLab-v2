import unittest

from gaon.learning import (
    AuditAction,
    AuditEvent,
    EvidenceRecord,
    EvidenceType,
    InMemoryLearningRepository,
    RelatedMemoryQuery,
    prepare_memory,
    research_goal_to_record,
    research_plan_to_record,
    research_session_to_outcome,
)
from gaon.research.brain import ResearchGoal, ResearchSession, ResearchSessionStatus, build_research_plan


class LearningMemoryRuntimeIntegrationTest(unittest.TestCase):
    def evidence(self) -> tuple[EvidenceRecord, ...]:
        return (
            EvidenceRecord(
                evidence_id="ev-runtime-001",
                evidence_type=EvidenceType.RESEARCH,
                reference="synthetic-runtime-fixture",
                summary="synthetic runtime integration evidence",
            ),
        )

    def test_research_to_learning_memory_runtime_round_trip(self) -> None:
        goal = ResearchGoal(
            goal_id="goal-runtime-001",
            question="Does ORB need volume confirmation?",
            scope="strategy-research",
            success_criteria=("evidence-backed candidate",),
            evidence=self.evidence(),
        )
        plan = build_research_plan(goal, plan_id="plan-runtime-001", steps=("backtest", "validate"))
        session = ResearchSession(
            session_id="session-runtime-001",
            goal=goal,
            plan=plan,
            status=ResearchSessionStatus.RUNNING,
            evidence=self.evidence(),
            notes=("volume filter improved stability",),
        ).transition(ResearchSessionStatus.COMPLETED, note="needs validation")
        outcome = research_session_to_outcome(session, project="StrategyLab", strategy="ORB", market="KRX")
        repository = InMemoryLearningRepository()
        records = (
            research_goal_to_record(goal, project="StrategyLab", strategy="ORB", market="KRX", created_at="2026-07-17T00:00:00Z"),
            research_plan_to_record(plan, scope=goal.scope, project="StrategyLab", strategy="ORB", market="KRX", created_at="2026-07-17T00:00:01Z"),
        )

        prepared = prepare_memory(repository, records)
        self.assertEqual(prepared.duplicate_candidates, ())
        self.assertEqual(outcome.research_goal_id, goal.goal_id)

        for record in prepared.proposed_records:
            repository.add(record)
            repository.append_audit(
                AuditEvent(
                    event_id=record.audit_ref,
                    actor="Codex",
                    action=AuditAction.CREATE,
                    target_ref=record.record_id,
                    before_version=None,
                    after_version=record.version,
                    scope=record.scope,
                    project=record.project,
                    strategy=record.strategy,
                    market=record.market,
                    evidence=record.evidence,
                    timestamp=record.created_at,
                    rollback_ref=None,
                )
            )

        related = repository.retrieve_related(
            RelatedMemoryQuery(
                scope="strategy-research",
                project="StrategyLab",
                strategy="ORB",
                market="KRX",
                query="volume confirmation",
                reference_time="2026-07-17T00:00:01Z",
            )
        )
        exported = repository.export_json()
        imported = InMemoryLearningRepository()
        imported.import_json(exported)
        imported_related = imported.retrieve_related(
            RelatedMemoryQuery(
                scope="strategy-research",
                project="StrategyLab",
                strategy="ORB",
                market="KRX",
                query="volume confirmation",
                reference_time="2026-07-17T00:00:01Z",
            )
        )

        self.assertEqual([result.record.record_id for result in related], [result.record.record_id for result in imported_related])
        self.assertEqual([event.event_id for event in imported.list_audit(action=AuditAction.CREATE)], [record.audit_ref for record in records])


if __name__ == "__main__":
    unittest.main()
