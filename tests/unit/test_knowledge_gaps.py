from __future__ import annotations

import unittest

from gaon.knowledge.conflicts import (
    ConflictStatus,
    KnowledgeConflictRecord,
)
from gaon.knowledge.gaps import (
    AutonomousResearchQueueBuilder,
    KnowledgeGapDetector,
    KnowledgeGapType,
    ResearchPriority,
    ResearchQuestionGenerator,
    canonical_question_id,
    gap_release_check,
)


TOPIC = "trend.regime.robustness"


def conflict(
    status: ConflictStatus,
    *,
    conflict_id: str = "knowledge-conflict:test",
) -> KnowledgeConflictRecord:
    return KnowledgeConflictRecord(
        conflict_id=conflict_id,
        topic_key=TOPIC,
        status=status,
        supporting_claim_ids=("claim:a",)
        if status is not ConflictStatus.NO_COMPARABLE_EVIDENCE
        else (),
        opposing_claim_ids=("claim:b",)
        if status is ConflictStatus.UNRESOLVED_CONFLICT
        else (),
        neutral_claim_ids=(),
        independent_source_count=2
        if status in {
            ConflictStatus.UNRESOLVED_CONFLICT,
            ConflictStatus.SUPPORTED,
        }
        else 1,
        supporting_source_count=1,
        opposing_source_count=1
        if status is ConflictStatus.UNRESOLVED_CONFLICT
        else 0,
        supporting_score=80,
        opposing_score=70
        if status is ConflictStatus.UNRESOLVED_CONFLICT
        else 0,
        reasons=("test",),
    )


class KnowledgeGapTests(unittest.TestCase):
    def test_unresolved_conflict_creates_contradiction_gap(self) -> None:
        result = KnowledgeGapDetector().detect(
            conflict(
                ConflictStatus.UNRESOLVED_CONFLICT
            )
        )
        self.assertEqual(
            result,
            KnowledgeGapType.CONTRADICTION,
        )

    def test_insufficient_independence_creates_gap(self) -> None:
        result = KnowledgeGapDetector().detect(
            conflict(
                ConflictStatus.INSUFFICIENT_INDEPENDENCE
            )
        )
        self.assertEqual(
            result,
            KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        )

    def test_no_comparable_evidence_creates_gap(self) -> None:
        result = KnowledgeGapDetector().detect(
            conflict(
                ConflictStatus.NO_COMPARABLE_EVIDENCE
            )
        )
        self.assertEqual(
            result,
            KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE,
        )

    def test_supported_state_creates_no_gap(self) -> None:
        result = KnowledgeGapDetector().detect(
            conflict(
                ConflictStatus.SUPPORTED
            )
        )
        self.assertIsNone(result)

    def test_question_id_is_deterministic(self) -> None:
        first = canonical_question_id(
            topic_key=TOPIC,
            gap_type=KnowledgeGapType.CONTRADICTION,
            parent_conflict_id="knowledge-conflict:test",
        )
        second = canonical_question_id(
            topic_key=TOPIC,
            gap_type=KnowledgeGapType.CONTRADICTION,
            parent_conflict_id="knowledge-conflict:test",
        )
        self.assertEqual(first, second)

    def test_conflict_generates_high_priority_question(self) -> None:
        source = conflict(
            ConflictStatus.UNRESOLVED_CONFLICT
        )

        questions = ResearchQuestionGenerator().generate(
            source
        )

        self.assertEqual(len(questions), 1)
        question = questions[0]

        self.assertEqual(
            question.gap_type,
            KnowledgeGapType.CONTRADICTION,
        )
        self.assertEqual(
            question.priority,
            ResearchPriority.HIGH,
        )
        self.assertEqual(
            question.parent_conflict_id,
            source.conflict_id,
        )
        self.assertGreater(
            len(question.required_evidence),
            0,
        )
        self.assertGreater(
            len(question.stop_conditions),
            0,
        )

    def test_supported_state_generates_no_question(self) -> None:
        questions = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.SUPPORTED
            )
        )
        self.assertEqual(questions, ())

    def test_question_never_auto_validates_or_executes(self) -> None:
        question = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.UNRESOLVED_CONFLICT
            )
        )[0]

        self.assertFalse(question.knowledge_validated)
        self.assertFalse(question.production_approved)
        self.assertFalse(question.policy_applied)
        self.assertFalse(question.execution_authorized)

    def test_queue_is_deduplicated(self) -> None:
        question = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.UNRESOLVED_CONFLICT
            )
        )[0]

        queue = AutonomousResearchQueueBuilder().build(
            (question, question)
        )

        self.assertEqual(len(queue), 1)

    def test_queue_is_bounded_and_not_auto_executed(self) -> None:
        question = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.UNRESOLVED_CONFLICT
            )
        )[0]

        queue = AutonomousResearchQueueBuilder(
            default_max_attempts=2
        ).build((question,))

        self.assertEqual(queue[0].attempts, 0)
        self.assertEqual(queue[0].max_attempts, 2)
        self.assertEqual(queue[0].status, "pending")
        self.assertFalse(queue[0].auto_execute)

    def test_high_priority_orders_before_medium(self) -> None:
        high = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.UNRESOLVED_CONFLICT,
                conflict_id="knowledge-conflict:high",
            )
        )[0]

        medium = ResearchQuestionGenerator().generate(
            conflict(
                ConflictStatus.INSUFFICIENT_INDEPENDENCE,
                conflict_id="knowledge-conflict:medium",
            )
        )[0]

        queue = AutonomousResearchQueueBuilder().build(
            (medium, high)
        )

        self.assertEqual(
            queue[0].question.priority,
            ResearchPriority.HIGH,
        )

    def test_release_check(self) -> None:
        self.assertEqual(
            gap_release_check()["safety"],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
