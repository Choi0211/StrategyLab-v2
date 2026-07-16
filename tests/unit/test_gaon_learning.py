import unittest

from gaon.learning import (
    AutonomousAction,
    ConfidenceScore,
    EvidenceRecord,
    EvidenceType,
    KnowledgeItem,
    KnowledgeStatus,
    LearningMemoryKind,
    LearningMemoryRecord,
    LearningMemoryStore,
    PolicyUpdateCandidate,
    transition_knowledge,
)


class GaonLearningTest(unittest.TestCase):
    def evidence(self) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id="ev-001",
            evidence_type=EvidenceType.EXPERIMENT,
            reference="synthetic sprint 11 fixture",
            summary="fixture validates Learning Memory rules",
        )

    def test_learning_memory_requires_evidence(self) -> None:
        with self.assertRaises(ValueError):
            LearningMemoryRecord(
                memory_id="mem-001",
                kind=LearningMemoryKind.RESEARCH_GOAL,
                content="research Korean equity intraday patterns",
                evidence=(),
            )

    def test_learning_memory_store_groups_by_required_kind(self) -> None:
        record = LearningMemoryRecord(
            memory_id="mem-001",
            kind=LearningMemoryKind.USER_PREFERENCE,
            content="Korean documentation preferred",
            evidence=(self.evidence(),),
        )
        store = LearningMemoryStore()
        store.add(record)

        self.assertEqual(store.get("mem-001"), record)
        self.assertEqual(store.by_kind(LearningMemoryKind.USER_PREFERENCE), (record,))

    def test_learning_memory_defines_required_categories(self) -> None:
        self.assertEqual(
            {kind.value for kind in LearningMemoryKind},
            {
                "research_goal",
                "research_plan",
                "experiment",
                "backtest_result",
                "validation_result",
                "failure_reason",
                "success_pattern",
                "user_preference",
                "knowledge",
                "citation",
                "conversation_summary",
            },
        )

    def test_knowledge_cannot_validate_without_user_approval(self) -> None:
        item = KnowledgeItem(
            knowledge_id="kn-001",
            topic="learning memory",
            statement="Knowledge requires evidence before promotion.",
            status=KnowledgeStatus.NEED_VALIDATION,
            evidence=(self.evidence(),),
            confidence=ConfidenceScore(0.8, "fixture evidence"),
        )

        with self.assertRaises(PermissionError):
            transition_knowledge(item, KnowledgeStatus.VALIDATED)

        validated = transition_knowledge(item, KnowledgeStatus.VALIDATED, user_approved=True)
        self.assertEqual(validated.status, KnowledgeStatus.VALIDATED)

    def test_policy_update_requires_evidence_rollback_and_approval(self) -> None:
        candidate = PolicyUpdateCandidate(
            policy_id="policy-001",
            proposed_change="prefer blueprint before implementation",
            evidence=(self.evidence(),),
            rollback_ref="policy-001-v0",
        )

        self.assertFalse(candidate.is_approved)
        approved = candidate.approve("Choi Youngha")
        self.assertTrue(approved.is_approved)

    def test_forbidden_autonomous_actions_are_explicit(self) -> None:
        self.assertEqual(
            {action.value for action in AutonomousAction},
            {
                "modify_source_code",
                "change_prompt",
                "operate_champion",
                "change_secret",
                "change_trading_rule",
                "delete_user_preference",
            },
        )


if __name__ == "__main__":
    unittest.main()
