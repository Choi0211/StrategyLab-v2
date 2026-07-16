import dataclasses
import inspect
import json
from pathlib import Path
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
    PreferenceApproval,
    RelatedMemoryQuery,
    ResearchOutcome,
    RevalidationSchedule,
    RevalidationStatus,
    prepare_memory,
    research_goal_to_record,
    research_plan_to_record,
    research_session_to_outcome,
)
import gaon.learning.detection as detection
from gaon.learning.fixtures import GOLDEN_LEARNING_RECORD_JSON, MIGRATION_V1_LEARNING_RECORD_JSON
from gaon.research.brain import ResearchGoal, ResearchSession, ResearchSessionStatus, build_research_plan


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "learning_memory"


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
        record_type: LearningRecordType = LearningRecordType.KNOWLEDGE_CLAIM,
        evidence: tuple[EvidenceRecord, ...] | None = None,
        **scope: str,
    ) -> LearningRecord:
        resolved_scope = {**self.scope(), **scope}
        return LearningRecord(
            record_id=record_id,
            record_type=record_type,
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

    def test_scope_and_record_type_filters(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-001", record_type=LearningRecordType.KNOWLEDGE_CLAIM))
        repository.add(self.record("record-002", record_type=LearningRecordType.RESEARCH_OUTCOME))

        matches = repository.filter(scope="strategy-research", record_type=LearningRecordType.RESEARCH_OUTCOME)

        self.assertEqual([record.record_id for record in matches], ["record-002"])

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

    def test_non_utc_offset_rejection(self) -> None:
        with self.assertRaises(ValueError):
            self.record("record-001", created_at="2026-07-17T01:00:00+09:00")

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

    def test_audit_action_query(self) -> None:
        repository = InMemoryLearningRepository()
        repository.append_audit(self.audit("audit-001", "record-001"))
        repository.append_audit(
            AuditEvent(
                event_id="audit-002",
                actor="Codex",
                action=AuditAction.MIGRATE,
                target_ref="record-001",
                before_version=1,
                after_version=1,
                evidence=self.evidence(),
                timestamp="2026-07-17T00:00:01Z",
                rollback_ref="repository-v0",
                **self.scope(),
            )
        )

        events = repository.list_audit(target_ref="record-001", action=AuditAction.MIGRATE)

        self.assertEqual([event.event_id for event in events], ["audit-002"])

    def test_related_retrieval_deterministic_ranking_and_breakdown(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-001", content="ORB needs volume confirmation.", created_at="2026-07-17T00:00:00Z"))
        repository.add(self.record("record-002", content="RSI mean reversion note.", created_at="2026-07-16T00:00:00Z", strategy="RSI"))

        results = repository.retrieve_related(
            RelatedMemoryQuery(
                scope="strategy-research",
                project="StrategyLab",
                strategy="ORB",
                market="KRX",
                query="volume confirmation",
                reference_time="2026-07-17T00:00:00Z",
            )
        )

        self.assertEqual(results[0].record.record_id, "record-001")
        self.assertGreater(results[0].score_breakdown.topic_match, 0.0)
        self.assertEqual(results[0].conflict_state, "clear")

    def test_conflict_and_revalidation_penalty_in_retrieval(self) -> None:
        repository = InMemoryLearningRepository()
        record = self.record("record-001")
        penalized = LearningRecord.from_dict(
            {
                **record.to_dict(),
                "confidence": {
                    **record.confidence.to_dict(),
                    "conflict_penalty": 1.0,
                    "validation_state": "need_validation",
                },
                "revalidation": {
                    **record.revalidation.to_dict(),
                    "due_at": "2026-07-01T00:00:00Z",
                },
            }
        )
        repository.add(penalized)

        result = repository.retrieve_related(
            RelatedMemoryQuery(
                scope="strategy-research",
                project="StrategyLab",
                strategy="ORB",
                market="KRX",
                query="ORB",
                reference_time="2026-07-17T00:00:00Z",
            )
        )[0]

        self.assertEqual(result.conflict_state, "conflict")
        self.assertEqual(result.revalidation_state, "overdue")
        self.assertLess(result.score_breakdown.conflict_penalty, 0.0)

    def test_json_repository_round_trip(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("record-001"))
        repository.append_audit(self.audit("audit-001", "record-001"))

        restored = InMemoryLearningRepository()
        restored.import_json(repository.export_json())

        self.assertEqual(restored.get("record-001"), repository.get("record-001"))
        self.assertEqual(restored.list_audit()[0].event_id, "audit-001")

    def test_fixture_import_and_migration(self) -> None:
        repository = InMemoryLearningRepository()
        repository.import_json((FIXTURE_DIR / "valid_repository_v1.json").read_text(encoding="utf-8"))
        self.assertTrue(repository.exists("record-001"))

        legacy = InMemoryLearningRepository()
        legacy.import_json((FIXTURE_DIR / "legacy_repository_v0.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy.list_all(), ())

    def test_invalid_import_fixtures_fail_closed(self) -> None:
        for fixture_name in (
            "unsupported_repository_v2.json",
            "duplicate_record_ids.json",
            "invalid_timestamp.json",
            "missing_evidence.json",
            "malformed_repository.json",
        ):
            with self.subTest(fixture_name=fixture_name):
                repository = InMemoryLearningRepository()
                with self.assertRaises(ValueError):
                    repository.import_json((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))

    def test_golden_json_fixture_loading(self) -> None:
        record = LearningRecord.from_json(GOLDEN_LEARNING_RECORD_JSON)

        self.assertEqual(record.record_id, "record-001")
        self.assertEqual(record.created_at, "2026-07-17T00:00:00Z")

    def test_migration_fixture_compatibility(self) -> None:
        record = LearningRecord.from_json(MIGRATION_V1_LEARNING_RECORD_JSON)

        payload = json.loads(record.to_json())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["kind"], "learning_record")

    def test_deep_immutable_metrics_protection(self) -> None:
        outcome = ResearchOutcome(
            outcome_id="outcome-001",
            research_goal_id="goal-001",
            experiment_id="exp-001",
            result_summary="fixture result",
            metrics={"sharpe": 1.2},
            conclusion="needs validation",
            evidence=self.evidence(),
            confidence=self.confidence(),
            **self.scope(),
        )

        with self.assertRaises(TypeError):
            outcome.metrics["sharpe"] = 0.0

    def test_preference_approval_type_separation(self) -> None:
        approval = PreferenceApproval(
            approval_id="pref-approval-001",
            preference_id="pref-001",
            approved_by="Choi Youngha",
            approved_at="2026-07-17T00:00:00Z",
            evidence=self.evidence(),
            **self.scope(),
        )

        self.assertEqual(PreferenceApproval.from_json(approval.to_json()), approval)
        self.assertNotIsInstance(approval, PolicyApproval)

    def test_research_brain_conversion_and_prepare_does_not_auto_save(self) -> None:
        goal = ResearchGoal(
            goal_id="goal-001",
            question="Does ORB need volume confirmation?",
            scope="strategy-research",
            success_criteria=("evidence-backed result",),
            evidence=self.evidence(),
        )
        plan = build_research_plan(goal, plan_id="plan-001", steps=("backtest", "validate"))
        session = ResearchSession(
            session_id="session-001",
            goal=goal,
            plan=plan,
            status=ResearchSessionStatus.RUNNING,
            evidence=self.evidence(),
            notes=("volume filter improved stability",),
        ).transition(ResearchSessionStatus.COMPLETED, note="needs validation")
        repository = InMemoryLearningRepository()
        goal_record = research_goal_to_record(goal, project="StrategyLab", strategy="ORB", market="KRX", created_at="2026-07-17T00:00:00Z")
        plan_record = research_plan_to_record(plan, scope=goal.scope, project="StrategyLab", strategy="ORB", market="KRX", created_at="2026-07-17T00:00:01Z")
        outcome = research_session_to_outcome(session, project="StrategyLab", strategy="ORB", market="KRX")

        prepared = prepare_memory(repository, (goal_record, plan_record))

        self.assertEqual(len(prepared.proposed_records), 2)
        self.assertEqual(repository.list_all(), ())
        self.assertEqual(outcome.research_goal_id, goal.goal_id)

    def test_no_db_vector_external_api_private_or_live_imports(self) -> None:
        import gaon.learning.repository as repository
        import gaon.learning.retrieval as retrieval
        import gaon.learning.serialization as serialization
        import gaon.learning.time as time

        combined_source = "\n".join(
            (
                inspect.getsource(repository),
                inspect.getsource(detection),
                inspect.getsource(retrieval),
                inspect.getsource(serialization),
                inspect.getsource(time),
            )
        )
        forbidden = ("sqlite", "sqlalchemy", "chromadb", "faiss", "embedding", "openai", "kis", "broker", "MyMoneyGuard")
        for item in forbidden:
            self.assertNotIn(item, combined_source)


if __name__ == "__main__":
    unittest.main()
