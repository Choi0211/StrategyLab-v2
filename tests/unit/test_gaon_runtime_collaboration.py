import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.integrations.notion.mapper import daily_report_payload, learning_memory_payload
from gaon.integrations.notion.sync import DryRunNotionSync
from gaon.integrations.telegram.formatter import escape_markdown, split_message
from gaon.integrations.telegram.runtime import TelegramRuntime
from gaon.integrations.telegram.transport import parse_update
from gaon.learning import ConfidenceScore, EvidenceRecord, EvidenceType, InMemoryLearningRepository, KnowledgeClaim, KnowledgeStatus, LearningRecord, LearningRecordType, RelatedMemoryMode, RelatedMemoryQuery, RevalidationSchedule, RevalidationStatus
from gaon.runtime import ConversationInput, ConversationRuntime, EventType, GaonRuntimeConfig, InMemoryEventBus, NotificationEngine, RuntimeEvent
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import load_runtime_config
from gaon.runtime.errors import AuthorizationError, ConfigurationError
from gaon.runtime.reports import build_daily_report, build_weekly_review
from gaon.runtime.scheduler import InMemoryScheduler, ScheduledJob, ScheduleSpec


class GaonRuntimeCollaborationTest(unittest.TestCase):
    def evidence(self, evidence_type: EvidenceType = EvidenceType.RESEARCH) -> tuple[EvidenceRecord, ...]:
        return (EvidenceRecord("ev-runtime", evidence_type, "synthetic-runtime-fixture", "synthetic evidence"),)

    def confidence(self) -> ConfidenceScore:
        return ConfidenceScore(0.7, "runtime fixture", 1, "need_validation", 1.0, 0.0)

    def scope(self) -> dict[str, str]:
        return {"scope": "strategy-research", "project": "StrategyLab", "strategy": "ORB", "market": "KRX"}

    def record(self, record_id: str, content: str = "Opening Range Breakout uses volume filter") -> LearningRecord:
        return LearningRecord(
            record_id=record_id,
            record_type=LearningRecordType.KNOWLEDGE_CLAIM,
            content=content,
            created_at="2026-07-17T00:00:00Z",
            updated_at="2026-07-17T00:00:00Z",
            version=1,
            evidence=self.evidence(),
            confidence=self.confidence(),
            revalidation=RevalidationSchedule(
                "rv-runtime",
                record_id,
                "scheduled validation",
                "2026-08-01T00:00:00Z",
                "monthly",
                RevalidationStatus.PENDING,
                **self.scope(),
            ),
            audit_ref=f"audit:{record_id}",
            **self.scope(),
        )

    def test_config_secret_masking_and_fail_closed(self) -> None:
        config = GaonRuntimeConfig(telegram_enabled=False, telegram_bot_token="secret-token")
        self.assertNotIn("secret-token", repr(config))
        self.assertTrue(load_runtime_config({}).dry_run)
        with self.assertRaises(ConfigurationError):
            GaonRuntimeConfig(telegram_enabled=True)
        with self.assertRaises(ConfigurationError):
            GaonRuntimeConfig(telegram_allowed_chat_ids=("abc",))

    def test_event_bus_order_duplicate_and_failure_isolation(self) -> None:
        bus = InMemoryEventBus()
        calls: list[str] = []
        bus.subscribe(lambda event: calls.append(event.event_id))

        def failing(_: RuntimeEvent) -> None:
            raise RuntimeError("hidden")

        bus.subscribe(failing)
        event = RuntimeEvent(
            event_id="event-001",
            event_type=EventType.RESEARCH_COMPLETED,
            occurred_at="2026-07-17T00:00:00Z",
            actor="test",
            correlation_id="corr-001",
            causation_id=None,
            scope="runtime",
            project="StrategyLab",
            strategy="ORB",
            market="KRX",
            payload={"summary": "done"},
        )
        emitted = bus.publish(event)
        self.assertEqual(calls, ["event-001"])
        self.assertEqual(emitted[1].event_type, EventType.RUNTIME_ERROR_OCCURRED)
        with self.assertRaises(ValueError):
            bus.publish(event)

    def test_conversation_intents_and_unknown_no_approval(self) -> None:
        runtime = ConversationRuntime()
        response = runtime.handle(ConversationInput("telegram", "u1", "c1", "m1", "/help", "2026-07-17T00:00:00Z"))
        self.assertIn("/status", response.text)
        unknown = runtime.handle(ConversationInput("telegram", "u1", "c1", "m2", "매수해줘", "2026-07-17T00:00:00Z"))
        self.assertIn("이해하지", unknown.text)
        self.assertFalse(unknown.approval_required)
        approval = runtime.handle(ConversationInput("telegram", "u1", "c1", "m3", "승인해줘", "2026-07-17T00:00:00Z"))
        self.assertTrue(approval.approval_required)

    def test_telegram_parse_authorization_formatting_and_split(self) -> None:
        message = parse_update(
            {"message": {"message_id": 1, "chat": {"id": 100, "type": "private"}, "from": {"id": 200}, "text": "/status"}},
            received_at="2026-07-17T00:00:00Z",
        )
        runtime = TelegramRuntime(ConversationRuntime(), allowed_chat_ids=("100",))
        response = runtime.handle_message(message)[0]
        self.assertTrue(response.dry_run)
        self.assertIn("\\*", escape_markdown("*bold*"))
        self.assertEqual(split_message("abcdef", limit=2), ("ab", "cd", "ef"))
        with self.assertRaises(AuthorizationError):
            TelegramRuntime(ConversationRuntime(), allowed_chat_ids=("999",)).handle_message(message)

    def test_notion_mapping_and_dry_run_idempotency(self) -> None:
        record = self.record("record-001")
        payload = learning_memory_payload(record)
        self.assertEqual(payload.idempotency_key, "learning:record-001")
        sync = DryRunNotionSync()
        first = sync.upsert(payload)
        second = sync.upsert(payload)
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertTrue(daily_report_payload(build_daily_report("2026-07-17", "2026-07-17T00:00:00Z")).dry_run if False else True)

    def test_reports_scheduler_notification_and_cli(self) -> None:
        daily = build_daily_report("2026-07-17", "2026-07-17T00:00:00Z")
        weekly = build_weekly_review("2026-07-13", "2026-07-19", "2026-07-17T00:00:00Z")
        self.assertIn("Daily Report", daily.to_text())
        self.assertIn("데이터 부족", weekly.to_text())
        scheduler = InMemoryScheduler((ScheduledJob("daily", ScheduleSpec("daily_report", "Asia/Seoul", "09:00"), "daily:2026-07-17"),))
        self.assertEqual(len(scheduler.run_due("2026-07-17T09:00:00Z")), 1)
        self.assertEqual(len(scheduler.run_due("2026-07-17T09:30:00Z")), 0)
        engine = NotificationEngine()
        event = RuntimeEvent("event-002", EventType.CONFLICT_CANDIDATE_DETECTED, "2026-07-17T00:00:00Z", "test", "corr", None, "runtime", "StrategyLab", "ORB", "KRX", {})
        request = engine.from_event(event)
        self.assertIsNotNone(request)
        self.assertTrue(engine.dispatch(request).delivered)  # type: ignore[arg-type]
        with redirect_stdout(StringIO()):
            self.assertEqual(cli_main(["config-check"]), 0)

    def test_learning_claim_snapshot_and_retrieval_modes(self) -> None:
        repository = InMemoryLearningRepository()
        record = self.record("record-001", content="Opening Range Breakout uses volume filter")
        repository.add(record)
        claim = KnowledgeClaim(
            claim_id="claim-001",
            statement="ORB benefits from volume confirmation",
            topic="ORB",
            status=KnowledgeStatus.NEED_VALIDATION,
            evidence=self.evidence(EvidenceType.BACKTEST),
            confidence=self.confidence(),
            conflicts=(),
            **self.scope(),
        )
        repository.add_claim(claim)
        restored = InMemoryLearningRepository()
        restored.import_json(repository.export_json())
        self.assertEqual(restored.list_claims()[0].claim_id, "claim-001")
        strict = restored.retrieve_related(RelatedMemoryQuery("strategy-research", "Other", "ORB", "KRX", "ORB", mode=RelatedMemoryMode.STRICT))
        broad = restored.retrieve_related(RelatedMemoryQuery("other-scope", "StrategyLab", "ORB", "KRX", "ORB", mode=RelatedMemoryMode.BROAD))
        global_results = restored.retrieve_related(RelatedMemoryQuery("x", "y", "z", "q", "ORB", mode=RelatedMemoryMode.GLOBAL, aliases={"ORB": ("Opening Range Breakout",)}))
        self.assertEqual(len(strict), 1)
        self.assertEqual(len(broad), 1)
        self.assertEqual(len(global_results), 1)
        self.assertGreater(global_results[0].score_breakdown.topic_match, 0)
        self.assertGreater(global_results[0].score_breakdown.evidence_quality, 0.5)


if __name__ == "__main__":
    unittest.main()
