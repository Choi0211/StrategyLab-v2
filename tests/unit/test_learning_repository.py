import dataclasses
import inspect
import json
import unittest

from gaon.learning import (
    AuditAction,
    AuditEvent,
    ConfidenceScore,
    EvidenceRecord,
    EvidenceType,
    InMemoryLearningRepository,
    KnowledgeApproval,
    KnowledgeClaim,
    KnowledgeStatus,
    LearningRecord,
    LearningRecordType,
    PolicyApproval,
    PolicyRevision,
    RevalidationSchedule,
    RevalidationStatus,
)
import gaon.learning.detection as detection
from gaon.learning.fixtures import GOLDEN_LEARNING_RECORD_JSON, MIGRATION_V1_LEARNING_RECORD_JSON


class LearningRepositoryTest(unittest.TestCase):
    def evidence(self, evidence_id: str = "ev-001", reference: str = "research-note-001") -> tuple[EvidenceRecord, ...]:
        return (
            EvidenceRecord(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.RESEARCH,
                reference=reference,
                summary="evidence-backed repository fixture",
            ),
        )

    def confidence(self) -> ConfidenceScore:
        return ConfidenceScore(
            value=0.7,
            reason="repository fixture confidence",
            evidence_count=1,
            validation_state="need_validation",
            recency=0.5,
            conflict_penalty=0.0,
        )

    def scope(
        self,
        project: str = "StrategyLab",
        strategy: str = "ORB",
        market: str = "KRX",
    ) -> dict[str, str]:
        return {
            "scope": "strategy-research",
            "project": project,
            "strategy": strategy,
            "market": market,
        }

    def revalidation(self, target_ref: str = "record-001") -> RevalidationSchedule:
        return RevalidationSchedule(
            schedule_id=f"rv-{target_ref}",
            target_ref=target_ref,
            reason="scheduled validation",
            due_at="2026-08-01T00:00:00Z",
            frequency="monthly",
            status=RevalidationStatus.PENDING,
            **self.scope(),
        )

    def record(
        self,
        record_id: str,
        content: str = "ORB needs volume confirmation.",
        created_at: str = "2026-07-17T00:00:00Z",
        evidence: tuple[EvidenceRecord, ...] | None = None,
        **scope: str,
    ) -> LearningRecord:
        resolved_scope = {**self.scope(), **scope}
        return LearningRecord(
            record_id=record_id,
            record_type=LearningRecordType.KNOWLEDGE_CLAIM,
            content=content,
            created_at=created_at,
            updated_at=created_at,
            version=1,
            evidence=self.evidence() if evidence is None else evidence,
            confidence=self.confidence(),
            revalidation=self.revalidation(record_id),
            audit_ref=f"audit-{record_id}",
            **resolved_scope,
        )

    def claim(
        self,
        claim_id: str,
        statement: str = "Volume confirmation improves ORB quality.",
        topic: str = "orb-volume",
        status: KnowledgeStatus = KnowledgeStatus.NEED_VALIDATION,
        conflicts: tuple[str, ...] = (),
        **scope: str,
    ) -> KnowledgeClaim:
        resolved_scope = {**self.scope(), **scope}
        return KnowledgeClaim(
            claim_id=claim_id,
            statement=statement,
            topic=topic,
            status=status,
            evidence=self.evidence(),
            confidence=self.confidence(),
            conflicts=conflicts,
            **resolved_scope,
        )

    def audit(self, event_id: str, target_ref: str) -> AuditEvent:
        return AuditEvent(
            event_id=event_id,
            actor="Codex",
            action=AuditAction.CREATE,
            target_ref=target_ref,
            before_version=None,
            after_version=1,
            evidence=self.evidence(),
            timestamp="2026-07-17T00:00:00Z",
            rollback_ref=None,
            **self.scope(),
        )

    def test_duplicate_id_rejection(self) -> None:
        repository = InMemoryLearningRepository()
        record = self.record("record-001")

        repository.add(record)

        with self.assertRaises(ValueError):
            repository.add(record)

    def test_immutable_copy_protection(self) -> None:
        repository = InMemoryLearningRepository()
        original = self.record("record-001")

        repository.add(original)
        retrieved = repository.get("record-001")

        self.assertEqual(original, retrieved)
        self.assertIsNot(original, retrieved)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            retrieved.content = "mutated"  # type: ignore[misc]
        self.assertEqual(repository.get("record-001").content, original.content)

    def test_chronological_ordering_is_explicit_and_deterministic(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-003", created_at="2026-07-17T00:00:02Z"))
        repository.add(self.record("record-001", created_at="2026-07-17T00:00:00Z"))
        repository.add(self.record("record-002", created_at="2026-07-17T00:00:00Z"))

        self.assertEqual(
            [record.record_id for record in repository.list_chronological()],
            ["record-001", "record-002", "record-003"],
        )

    def test_project_strategy_market_filters_are_and_conditions(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-001", project="StrategyLab", strategy="ORB", market="KRX"))
        repository.add(self.record("record-002", project="StrategyLab", strategy="ORB", market="NASDAQ"))
        repository.add(self.record("record-003", project="StrategyLab", strategy="RSI", market="KRX"))

        matches = repository.filter(project="StrategyLab", strategy="ORB", market="KRX")

        self.assertEqual([record.record_id for record in matches], ["record-001"])

    def test_duplicate_candidate_detection_does_not_merge(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-001", content="ORB needs volume confirmation."))
        candidate = self.record("record-002", content="  orb   needs volume confirmation.  ")

        duplicates = repository.find_duplicates(candidate)

        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].existing_id, "record-001")
        self.assertEqual(repository.list_all()[0].record_id, "record-001")

    def test_conflict_candidate_detection_does_not_resolve(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add_claim(self.claim("claim-001", statement="ORB should use volume confirmation."))
        candidate = self.claim("claim-002", statement="ORB should not use volume confirmation.")

        conflicts = repository.find_conflicts(candidate)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].existing_id, "claim-001")

    def test_knowledge_approval_scope_mismatch_rejection(self) -> None:
        claim = self.claim("claim-001")
        approval = KnowledgeApproval(
            approval_id="ka-001",
            claim_id=claim.claim_id,
            approved_by="Choi Youngha",
            approved_at="2026-07-17T00:00:00Z",
            evidence=self.evidence(),
            **self.scope(market="NASDAQ"),
        )

        with self.assertRaises(ValueError):
            claim.validate(approval)

    def test_policy_approval_scope_and_rollback_mismatch_rejection(self) -> None:
        revision = PolicyRevision(
            revision_id="policy-rev-001",
            policy_ref="research-policy",
            proposed_change="prefer evidence-first research plans",
            previous_version=1,
            next_version=2,
            evidence=self.evidence(),
            rollback_ref="research-policy-v1",
            **self.scope(),
        )
        wrong_scope = PolicyApproval(
            approval_id="pa-001",
            revision_id=revision.revision_id,
            approved_by="Choi Youngha",
            approved_at="2026-07-17T00:00:00Z",
            evidence=self.evidence(),
            rollback_ref=revision.rollback_ref,
            **self.scope(strategy="RSI"),
        )
        wrong_rollback = PolicyApproval(
            approval_id="pa-002",
            revision_id=revision.revision_id,
            approved_by="Choi Youngha",
            approved_at="2026-07-17T00:00:00Z",
            evidence=self.evidence(),
            rollback_ref="different-rollback",
            **self.scope(),
        )

        with self.assertRaises(ValueError):
            revision.apply(wrong_scope)
        with self.assertRaises(ValueError):
            revision.apply(wrong_rollback)

    def test_invalid_timestamp_rejection(self) -> None:
        with self.assertRaises(ValueError):
            self.record("record-001", created_at="2026-07-17T09:00:00+09:00")
        with self.assertRaises(ValueError):
            self.record("record-002", created_at="2026-07-17")

    def test_append_only_audit_behavior(self) -> None:
        repository = InMemoryLearningRepository()
        event = self.audit("audit-001", "record-001")

        repository.append_audit(event)

        with self.assertRaises(ValueError):
            repository.append_audit(event)
        with self.assertRaises(PermissionError):
            repository.replace_audit(event)
        with self.assertRaises(PermissionError):
            repository.delete_audit(event.event_id)

    def test_audit_target_query(self) -> None:
        repository = InMemoryLearningRepository()
        repository.append_audit(self.audit("audit-001", "record-001"))
        repository.append_audit(self.audit("audit-002", "record-002"))

        events = repository.list_audit(target_ref="record-001")

        self.assertEqual([event.event_id for event in events], ["audit-001"])

    def test_golden_json_fixture_loading(self) -> None:
        record = LearningRecord.from_json(GOLDEN_LEARNING_RECORD_JSON)

        self.assertEqual(record.record_id, "record-001")
        self.assertEqual(record.created_at, "2026-07-17T00:00:00Z")

    def test_migration_fixture_compatibility(self) -> None:
        record = LearningRecord.from_json(MIGRATION_V1_LEARNING_RECORD_JSON)

        payload = json.loads(record.to_json())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["kind"], "learning_record")

    def test_no_db_vector_external_api_private_or_live_imports(self) -> None:
        import gaon.learning.repository as repository
        import gaon.learning.time as time

        combined_source = "\n".join(
            (
                inspect.getsource(repository),
                inspect.getsource(detection),
                inspect.getsource(time),
            )
        )
        forbidden = ("sqlite", "sqlalchemy", "chromadb", "faiss", "embedding", "openai", "kis", "broker", "MyMoneyGuard")
        for item in forbidden:
            self.assertNotIn(item, combined_source)


if __name__ == "__main__":
    unittest.main()
