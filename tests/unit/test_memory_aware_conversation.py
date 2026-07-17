import unittest

from gaon.learning import ConfidenceScore, EvidenceRecord, EvidenceType, InMemoryLearningRepository, LearningRecord, LearningRecordType, RevalidationSchedule, RevalidationStatus
from gaon.runtime import ConversationInput, ConversationRuntime
from gaon.runtime.intents import Intent
from gaon.runtime.memory_context import MemoryContextBuilder


class MemoryAwareConversationTest(unittest.TestCase):
    def evidence(self, suffix: str = "1") -> tuple[EvidenceRecord, ...]:
        return (EvidenceRecord(f"ev-{suffix}", EvidenceType.RESEARCH, f"fixture-{suffix}", "synthetic evidence"),)

    def record(
        self,
        record_id: str,
        content: str,
        *,
        project: str = "StrategyLab",
        strategy: str = "ORB",
        market: str = "KRX",
        scope: str = "strategy-research",
        validation_state: str = "validated",
        conflict_penalty: float = 0.0,
        due_at: str = "2026-08-01T00:00:00Z",
    ) -> LearningRecord:
        return LearningRecord(
            record_id=record_id,
            record_type=LearningRecordType.KNOWLEDGE_CLAIM,
            content=content,
            scope=scope,
            project=project,
            strategy=strategy,
            market=market,
            created_at="2026-07-17T00:00:00Z",
            updated_at="2026-07-17T00:00:00Z",
            version=1,
            evidence=self.evidence(record_id),
            confidence=ConfidenceScore(0.8, "fixture", 1, validation_state, 1.0, conflict_penalty),
            revalidation=RevalidationSchedule(f"rv-{record_id}", record_id, "scheduled", due_at, "monthly", RevalidationStatus.PENDING, scope, project, strategy, market),
            audit_ref=f"audit:{record_id}",
        )

    def message(self, text: str) -> ConversationInput:
        return ConversationInput("telegram", "u1", "c1", f"m-{text}", text, "2026-07-17T00:00:00Z")

    def test_strict_retrieval_and_no_mutation(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("r1", "ORB opening range breakout memory"))
        before = repository.export_json()
        runtime = ConversationRuntime(context_builder=MemoryContextBuilder(repository))

        response = runtime.handle(self.message("/memory ORB"))

        self.assertIn("관련 기록 1건", response.text)
        self.assertIn("r1", response.text)
        self.assertIn("ev-r1", response.references)
        self.assertIn("context", response.route)
        self.assertEqual(repository.export_json(), before)

    def test_broad_and_global_fallback(self) -> None:
        broad_repo = InMemoryLearningRepository()
        broad_repo.add(self.record("broad", "ORB broad match", project="Other", strategy="VWAP", market="NYSE"))
        broad_response = ConversationRuntime(context_builder=MemoryContextBuilder(broad_repo)).handle(self.message("/memory ORB"))
        self.assertIn("broad fallback used", broad_response.warnings)

        global_repo = InMemoryLearningRepository()
        global_repo.add(self.record("global", "unrelated fallback", project="Other", strategy="VWAP", market="NYSE", scope="other-scope"))
        global_response = ConversationRuntime(context_builder=MemoryContextBuilder(global_repo)).handle(self.message("/memory nothing"))
        self.assertIn("global fallback used", global_response.warnings)

    def test_no_result_conflict_revalidation_and_confidence_warning(self) -> None:
        empty = ConversationRuntime(context_builder=MemoryContextBuilder(InMemoryLearningRepository())).handle(self.message("/memory ORB"))
        self.assertIn("기록을 찾지 못했습니다", empty.text)

        repository = InMemoryLearningRepository()
        repository.add(self.record("risk", "ORB conflict revalidation", validation_state="need_validation", conflict_penalty=0.4, due_at="2026-07-01T00:00:00Z"))
        response = ConversationRuntime(context_builder=MemoryContextBuilder(repository)).handle(self.message("/memory ORB"))

        self.assertIn("아직 검증이 필요", response.text)
        self.assertIn("충돌 후보", response.text)
        self.assertIn("재검증", response.text)
        self.assertIn("Confidence는 정렬 보조 신호", response.text)

    def test_context_only_for_selected_intents(self) -> None:
        repository = InMemoryLearningRepository()
        repository.add(self.record("r1", "ORB memory"))
        response = ConversationRuntime(context_builder=MemoryContextBuilder(repository)).handle(self.message("안녕"))
        self.assertEqual(response.intent, Intent.GREETING)
        self.assertNotIn("관련 기록", response.text)


if __name__ == "__main__":
    unittest.main()
