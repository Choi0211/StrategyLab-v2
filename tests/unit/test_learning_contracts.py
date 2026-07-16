import dataclasses
import json
import unittest

from gaon.learning import (
    AuditAction,
    AuditEvent,
    ConfidenceScore,
    ConversationSummary,
    EvidenceRecord,
    EvidenceType,
    FailurePattern,
    KnowledgeApproval,
    KnowledgeClaim,
    KnowledgeStatus,
    LearningRecord,
    LearningRecordType,
    PolicyApproval,
    PolicyRevision,
    ResearchOutcome,
    RevalidationSchedule,
    RevalidationStatus,
    SuccessPattern,
    UserPreference,
)


class LearningContractsTest(unittest.TestCase):
    def evidence(self) -> tuple[EvidenceRecord, ...]:
        return (
            EvidenceRecord(
                evidence_id="ev-001",
                evidence_type=EvidenceType.RESEARCH,
                reference="sprint12 fixture",
                summary="evidence-backed contract fixture",
            ),
        )

    def confidence(self) -> ConfidenceScore:
        return ConfidenceScore(
            value=0.7,
            reason="evidence-backed but not approved",
            evidence_count=1,
            validation_state="need_validation",
            recency=0.5,
            conflict_penalty=0.0,
        )

    def scope(self) -> dict[str, str]:
        return {
            "scope": "strategy-research",
            "project": "StrategyLab",
            "strategy": "ORB",
            "market": "KRX",
        }

    def revalidation(self) -> RevalidationSchedule:
        return RevalidationSchedule(
            schedule_id="rv-001",
            target_ref="claim-001",
            reason="validate after new backtest",
            due_at="2026-08-01",
            frequency="monthly",
            status=RevalidationStatus.PENDING,
            **self.scope(),
        )

    def knowledge_claim(self) -> KnowledgeClaim:
        return KnowledgeClaim(
            claim_id="claim-001",
            statement="ORB needs volume confirmation.",
            topic="orb",
            status=KnowledgeStatus.NEED_VALIDATION,
            evidence=self.evidence(),
            confidence=self.confidence(),
            conflicts=(),
            **self.scope(),
        )

    def policy_revision(self) -> PolicyRevision:
        return PolicyRevision(
            revision_id="policy-rev-001",
            policy_ref="research-policy",
            proposed_change="prefer evidence-first research plans",
            previous_version=1,
            next_version=2,
            evidence=self.evidence(),
            rollback_ref="research-policy-v1",
            **self.scope(),
        )

    def test_evidence_required_for_learning_objects(self) -> None:
        with self.assertRaises(ValueError):
            KnowledgeClaim(
                claim_id="claim-empty",
                statement="missing evidence",
                topic="test",
                status=KnowledgeStatus.COLLECTED,
                evidence=(),
                confidence=self.confidence(),
                conflicts=(),
                **self.scope(),
            )
        with self.assertRaises(ValueError):
            UserPreference(
                preference_id="pref-empty",
                preference="Korean docs preferred",
                evidence=(),
                confidence=self.confidence(),
                version=1,
                **self.scope(),
            )

    def test_contracts_are_immutable(self) -> None:
        claim = self.knowledge_claim()

        self.assertTrue(dataclasses.is_dataclass(claim))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            claim.statement = "mutated"  # type: ignore[misc]

    def test_knowledge_approval_gate(self) -> None:
        claim = self.knowledge_claim()

        with self.assertRaises(PermissionError):
            claim.validate()

        approval = KnowledgeApproval(
            approval_id="ka-001",
            claim_id=claim.claim_id,
            approved_by="Choi Youngha",
            approved_at="2026-07-16",
            evidence=self.evidence(),
            **self.scope(),
        )
        validated = claim.validate(approval)
        self.assertEqual(validated.status, KnowledgeStatus.VALIDATED)
        self.assertEqual(validated.approval, approval)

    def test_policy_approval_and_rollback_gate(self) -> None:
        revision = self.policy_revision()

        with self.assertRaises(PermissionError):
            revision.apply()

        approval = PolicyApproval(
            approval_id="pa-001",
            revision_id=revision.revision_id,
            approved_by="Choi Youngha",
            approved_at="2026-07-16",
            evidence=self.evidence(),
            rollback_ref=revision.rollback_ref,
            **self.scope(),
        )
        applied = revision.apply(approval)
        self.assertTrue(applied.applied)
        self.assertEqual(applied.approval, approval)

    def test_confidence_cannot_approve(self) -> None:
        confidence = self.confidence()

        self.assertFalse(confidence.can_approve)
        with self.assertRaises(PermissionError):
            self.knowledge_claim().validate()  # confidence alone is intentionally ignored

    def test_preference_overwrite_prevention(self) -> None:
        preference = UserPreference(
            preference_id="pref-001",
            preference="Korean documentation preferred",
            evidence=self.evidence(),
            confidence=self.confidence(),
            version=1,
            **self.scope(),
        )

        with self.assertRaises(PermissionError):
            preference.overwrite_automatically("English documentation preferred")
        with self.assertRaises(PermissionError):
            preference.delete_automatically()
        proposal = preference.propose_change("proposal-001", "Add concise Korean summaries", self.evidence())
        self.assertTrue(proposal.approval_required)

    def test_json_round_trip_for_required_contracts(self) -> None:
        confidence = self.confidence()
        revalidation = self.revalidation()
        claim = self.knowledge_claim()
        outcome = ResearchOutcome(
            outcome_id="outcome-001",
            research_goal_id="goal-001",
            experiment_id="exp-001",
            result_summary="fixture result",
            metrics={"sharpe": 1.2},
            conclusion="needs validation",
            evidence=self.evidence(),
            confidence=confidence,
            **self.scope(),
        )
        failure = FailurePattern(
            failure_id="failure-001",
            cause="low volume",
            symptom="false breakout",
            context="opening range",
            avoidance_rule="require volume filter",
            evidence=self.evidence(),
            confidence=confidence,
            **self.scope(),
        )
        success = SuccessPattern(
            success_id="success-001",
            pattern="volume-confirmed breakout",
            context="opening range",
            repeatability_notes="validate monthly",
            evidence=self.evidence(),
            confidence=confidence,
            **self.scope(),
        )
        preference = UserPreference(
            preference_id="pref-001",
            preference="Blueprint first",
            evidence=self.evidence(),
            confidence=confidence,
            version=1,
            **self.scope(),
        )
        summary = ConversationSummary(
            summary_id="summary-001",
            conversation_ref="thread-001",
            summary="Sprint 12 planning",
            decisions=("design first",),
            todos=("implement contracts",),
            evidence=self.evidence(),
            confidence=confidence,
            **self.scope(),
        )
        revision = self.policy_revision()
        audit = AuditEvent(
            event_id="audit-001",
            actor="Codex",
            action=AuditAction.CREATE,
            target_ref=claim.claim_id,
            before_version=None,
            after_version=1,
            evidence=self.evidence(),
            timestamp="2026-07-16T00:00:00+09:00",
            rollback_ref=None,
            **self.scope(),
        )
        record = LearningRecord(
            record_id="record-001",
            record_type=LearningRecordType.KNOWLEDGE_CLAIM,
            content=claim.statement,
            created_at="2026-07-16T00:00:00+09:00",
            updated_at="2026-07-16T00:00:00+09:00",
            version=1,
            evidence=self.evidence(),
            confidence=confidence,
            revalidation=revalidation,
            audit_ref=audit.event_id,
            **self.scope(),
        )

        cases = (
            (ConfidenceScore, confidence),
            (RevalidationSchedule, revalidation),
            (KnowledgeClaim, claim),
            (ResearchOutcome, outcome),
            (FailurePattern, failure),
            (SuccessPattern, success),
            (UserPreference, preference),
            (ConversationSummary, summary),
            (PolicyRevision, revision),
            (AuditEvent, audit),
            (LearningRecord, record),
        )
        for cls, item in cases:
            self.assertEqual(cls.from_json(item.to_json()), item)

    def test_invalid_kind_and_version_rejection(self) -> None:
        payload = json.loads(self.knowledge_claim().to_json())
        payload["kind"] = "wrong_kind"
        with self.assertRaises(ValueError):
            KnowledgeClaim.from_json(json.dumps(payload))

        payload = json.loads(self.knowledge_claim().to_json())
        payload["schema_version"] = 999
        with self.assertRaises(ValueError):
            KnowledgeClaim.from_json(json.dumps(payload))

    def test_no_secret_private_or_live_trading_imports(self) -> None:
        import gaon.learning.contracts as contracts

        forbidden = ("kis", "broker", "MyMoneyGuard", "telegram", "dashboard", "openai")
        source_names = set(contracts.__dict__)
        for item in forbidden:
            self.assertNotIn(item, source_names)


if __name__ == "__main__":
    unittest.main()
