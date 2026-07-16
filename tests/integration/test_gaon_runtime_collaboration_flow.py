import unittest

from gaon.integrations.notion.mapper import daily_report_payload, weekly_review_payload
from gaon.integrations.notion.sync import DryRunNotionSync
from gaon.integrations.telegram.runtime import TelegramRuntime
from gaon.integrations.telegram.transport import parse_update
from gaon.learning import (
    ConfidenceScore,
    EvidenceRecord,
    EvidenceType,
    InMemoryLearningRepository,
    LearningRecord,
    LearningRecordType,
    RelatedMemoryQuery,
    RevalidationSchedule,
    RevalidationStatus,
)
from gaon.runtime import ConversationRuntime, EventType, InMemoryEventBus, NotificationEngine, RuntimeEvent
from gaon.runtime.reports import build_daily_report, build_weekly_review


class GaonRuntimeCollaborationIntegrationTest(unittest.TestCase):
    def record(self) -> LearningRecord:
        evidence = (EvidenceRecord("ev-int", EvidenceType.BACKTEST, "synthetic-integration-fixture", "backtest evidence"),)
        scope = {"scope": "strategy-research", "project": "StrategyLab", "strategy": "ORB", "market": "KRX"}
        return LearningRecord(
            record_id="record-int",
            record_type=LearningRecordType.KNOWLEDGE_CLAIM,
            content="ORB needs volume confirmation",
            created_at="2026-07-17T00:00:00Z",
            updated_at="2026-07-17T00:00:00Z",
            version=1,
            evidence=evidence,
            confidence=ConfidenceScore(0.8, "fixture", 1, "need_validation", 1.0, 0.0),
            revalidation=RevalidationSchedule("rv-int", "record-int", "scheduled", "2026-08-01T00:00:00Z", "monthly", RevalidationStatus.PENDING, **scope),
            audit_ref="audit:int",
            **scope,
        )

    def test_telegram_research_status_flow(self) -> None:
        bus = InMemoryEventBus()
        runtime = TelegramRuntime(ConversationRuntime(bus), allowed_chat_ids=("100",))
        message = parse_update(
            {"message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 200}, "text": "/status"}},
            received_at="2026-07-17T00:00:00Z",
        )

        responses = runtime.handle_message(message)

        self.assertIn("dry-run", responses[0].text)
        self.assertEqual(bus.list_events()[0].event_type, EventType.TELEGRAM_RESPONSE_PREPARED)

    def test_research_completion_notification_flow(self) -> None:
        event = RuntimeEvent("event-research-done", EventType.RESEARCH_COMPLETED, "2026-07-17T00:00:00Z", "test", "corr", None, "strategy-research", "StrategyLab", "ORB", "KRX", {"summary": "done"})
        engine = NotificationEngine()
        request = engine.from_event(event)
        self.assertIsNotNone(request)

        result = engine.dispatch(request)  # type: ignore[arg-type]

        self.assertTrue(result.delivered)
        self.assertTrue(result.dry_run)

    def test_daily_and_weekly_report_mapping_flow(self) -> None:
        notion = DryRunNotionSync()
        daily = build_daily_report("2026-07-17", "2026-07-17T00:00:00Z")
        weekly = build_weekly_review("2026-07-13", "2026-07-19", "2026-07-17T00:00:00Z")

        self.assertTrue(notion.upsert(daily_report_payload(daily)).success)
        self.assertTrue(notion.upsert(weekly_review_payload(weekly)).success)

    def test_repository_snapshot_same_memory_query_after_import(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record())
        restored = InMemoryLearningRepository()
        restored.import_json(repository.export_json())
        query = RelatedMemoryQuery("strategy-research", "StrategyLab", "ORB", "KRX", "volume", reference_time="2026-07-17T00:00:00Z")

        self.assertEqual(
            [result.record.record_id for result in repository.retrieve_related(query)],
            [result.record.record_id for result in restored.retrieve_related(query)],
        )


if __name__ == "__main__":
    unittest.main()
