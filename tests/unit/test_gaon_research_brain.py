import unittest

from gaon.learning import EvidenceRecord, EvidenceType, LearningMemoryKind
from gaon.research import (
    ResearchGoal,
    ResearchInterview,
    ResearchJournal,
    ResearchJournalEntry,
    ResearchJournalEntryType,
    ResearchPlan,
    ResearchSession,
    ResearchSessionStatus,
    build_research_plan,
)


class GaonResearchBrainTest(unittest.TestCase):
    def evidence(self) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id="ev-rb-001",
            evidence_type=EvidenceType.RESEARCH,
            reference="sprint 11 research brain fixture",
            summary="fixture validates Research Brain contracts",
        )

    def goal(self) -> ResearchGoal:
        return ResearchGoal(
            goal_id="goal-001",
            question="Research Korean equity intraday breakout patterns.",
            scope="public synthetic fixtures only",
            success_criteria=("create testable plan", "record evidence"),
            evidence=(self.evidence(),),
        )

    def test_research_goal_requires_evidence_and_exports_memory(self) -> None:
        with self.assertRaises(ValueError):
            ResearchGoal("goal-empty", "question", "scope", ("criterion",), ())

        memory = self.goal().to_memory_record()
        self.assertEqual(memory.kind, LearningMemoryKind.RESEARCH_GOAL)
        self.assertIn("Korean equity", memory.content)

    def test_research_plan_is_built_from_goal(self) -> None:
        goal = self.goal()
        plan = build_research_plan(
            goal,
            plan_id="plan-001",
            steps=("define fixture", "run V1 adapter later", "review evidence"),
            constraints=("no private data",),
        )

        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(plan.to_memory_record().kind, LearningMemoryKind.RESEARCH_PLAN)

    def test_research_plan_requires_steps(self) -> None:
        with self.assertRaises(ValueError):
            ResearchPlan("plan-empty", "goal-001", (), (), (self.evidence(),))

    def test_session_requires_goal_plan_match_and_tracks_status(self) -> None:
        goal = self.goal()
        plan = build_research_plan(goal, plan_id="plan-001", steps=("review evidence",))
        session = ResearchSession(
            session_id="session-001",
            goal=goal,
            plan=plan,
            status=ResearchSessionStatus.PLANNED,
            evidence=(self.evidence(),),
        )

        running = session.transition(ResearchSessionStatus.RUNNING, note="started review")
        self.assertEqual(running.status, ResearchSessionStatus.RUNNING)
        self.assertEqual(running.notes, ("started review",))

        other_plan = ResearchPlan("plan-other", "other-goal", ("step",), (), (self.evidence(),))
        with self.assertRaises(ValueError):
            ResearchSession("bad-session", goal, other_plan, ResearchSessionStatus.PLANNED, (self.evidence(),))

    def test_interview_requires_aligned_questions_and_answers(self) -> None:
        interview = ResearchInterview(
            interview_id="interview-001",
            goal_id="goal-001",
            questions=("What market?",),
            answers=("Korean equities with synthetic data first.",),
            evidence=(self.evidence(),),
        )

        self.assertEqual(interview.goal_id, "goal-001")
        with self.assertRaises(ValueError):
            ResearchInterview("bad", "goal-001", ("q1", "q2"), ("a1",), (self.evidence(),))

    def test_journal_is_immutable_and_rejects_duplicate_entries(self) -> None:
        entry = ResearchJournalEntry(
            entry_id="entry-001",
            entry_type=ResearchJournalEntryType.OBSERVATION,
            content="No private data used.",
            evidence=(self.evidence(),),
        )
        journal = ResearchJournal("journal-001", "session-001", ())
        updated = journal.add_entry(entry)

        self.assertEqual(journal.entries, ())
        self.assertEqual(updated.entries, (entry,))
        with self.assertRaises(ValueError):
            updated.add_entry(entry)


if __name__ == "__main__":
    unittest.main()
