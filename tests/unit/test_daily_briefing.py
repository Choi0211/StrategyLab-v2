from __future__ import annotations

import sqlite3
import unittest

from gaon.integrations.telegram.client import DryRunTelegramClient
from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.integrations.telegram.formatter import split_message
from gaon.knowledge.news_intelligence import NewsImpact, NewsIntelligenceItem
from gaon.research.research_director import ResearchDirector, ResearchDirectorAction, ResearchDirectorState
from gaon.runtime.daily_briefing import (
    DailyBriefingScheduler,
    compose_post_market_briefing,
    compose_pre_market_briefing,
    compose_unresolved_research_review,
    latest_research_mission_from_connection,
    production_daily_briefing_release_check,
    production_morning_briefing_research_state_consistency_release_check,
    render_post_market_briefing_ko,
    render_pre_market_briefing_ko,
    render_unresolved_research_review_ko,
    schedule_daily_briefing_jobs,
    send_daily_briefing,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.scheduled_automation import ScheduledJobRepository


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _news(item_id: str, importance: int, *, fixture_backed: bool = False) -> NewsIntelligenceItem:
    return NewsIntelligenceItem(
        item_id=item_id,
        headline=f"headline {item_id}",
        source="Wire",
        published_at="unknown",
        observed_at="2026-08-16T08:00:00Z",
        provider="production:news:rss",
        locator="https://news.google.com/x",
        content_hash="a" * 64,
        fixture_backed=fixture_backed,
        importance_score=importance,
        affected_markets=("KOSPI",),
        affected_symbols=("005930",),
        affected_sectors=(),
        impact=NewsImpact.UNCERTAIN,
        strategy_relevant=True,
        hypothesis_conflict="not_evaluated",
        research_action="hold",
    )


def _hold_decision() -> "ResearchDirectorDecision":
    return ResearchDirector().decide(
        ResearchDirectorState(
            evidence_strength="strong",
            hypothesis_conflict="supported",
            symbol_coverage_sufficient=True,
            period_sufficient=True,
            oos_completed=True,
            walk_forward_completed=True,
            regime_completed=True,
            cost_stress_completed=True,
            monte_carlo_completed=True,
            live_execution_available=False,
            live_execution_inspected=False,
            live_execution_failed_orders=0,
            candidate_rejected=False,
            steps_used=10,
            max_steps=10,
        )
    )


class DailyBriefingTests(unittest.TestCase):
    def test_pre_market_briefing_excludes_fixture_news_and_ranks_by_importance(self) -> None:
        low = _news("low", 20)
        high = _news("high", 90)
        fixture = _news("fixture", 99, fixture_backed=True)
        briefing = compose_pre_market_briefing(
            generated_at="2026-08-16T08:00:00Z", market="KOSPI", news_items=(low, fixture, high)
        )
        self.assertEqual(briefing.important_news, (high, low))

    def test_pre_market_briefing_rejects_non_utc_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            compose_pre_market_briefing(generated_at="2026-08-16T08:00:00+09:00", market="KOSPI")

    def test_post_market_briefing_reads_live_feedback_shaped_mapping(self) -> None:
        briefing = compose_post_market_briefing(
            generated_at="2026-08-16T15:40:00Z",
            market="KOSPI",
            live_feedback_json={
                "completed_trade_count": 4,
                "win_rate": 0.5,
                "failed_order_count": 2,
                "unconfirmed_order_count": 1,
                "unmatched_sell_count": 0,
                "open_position_count": 1,
                "classifications": ("execution_failure",),
            },
        )
        self.assertEqual(briefing.completed_trade_count, 4)
        self.assertEqual(briefing.failed_order_count, 2)
        self.assertIn("execution_failure", briefing.execution_classifications)

    def test_post_market_briefing_never_claims_mutation_or_order(self) -> None:
        briefing = compose_post_market_briefing(
            generated_at="2026-08-16T15:40:00Z", market="KOSPI", live_feedback_json={}
        )
        payload = briefing.to_json()
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])

    def test_render_post_market_briefing_separates_strategy_from_execution(self) -> None:
        briefing = compose_post_market_briefing(
            generated_at="2026-08-16T15:40:00Z",
            market="KOSPI",
            live_feedback_json={"completed_trade_count": 0, "failed_order_count": 1},
        )
        text = render_post_market_briefing_ko(briefing)
        self.assertIn("[전략 성과", text)
        self.assertIn("[주문 실행 이슈", text)
        self.assertIn("확정된 왕복 거래가 없어", text)
        self.assertIn("전략 손익이 아닌 실행 리스크", text)

    def test_render_pre_market_briefing_is_honest_when_no_news(self) -> None:
        briefing = compose_pre_market_briefing(generated_at="2026-08-16T08:00:00Z", market="KOSPI")
        text = render_pre_market_briefing_ko(briefing)
        self.assertIn("반영할 만한 새 뉴스 근거가 없습니다", text)
        self.assertIn("새 뉴스에서 파생된 추가 연구 항목은 없습니다", text)
        self.assertNotIn("추가로 필요한 연구가 없습니다", text)
        self.assertIn("기준 시각: 2026-08-16 17:00 KST", text)

    def test_pre_market_briefing_separates_news_and_active_research_mission(self) -> None:
        from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, next_candidate_sequence
        from gaon.knowledge.strategy_candidate import new_candidate

        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요",
            existing=None,
            now="2026-08-22T00:00:05Z",
        )
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now="2026-08-22T00:00:05Z")
        mission = add_candidate(mission, candidate, now="2026-08-22T00:00:05Z")
        briefing = compose_pre_market_briefing(
            generated_at="2026-08-22T00:00:05Z",
            market="KOSPI",
            research_mission=mission,
        )
        text = render_pre_market_briefing_ko(briefing)
        self.assertIn("[뉴스]", text)
        self.assertIn("새 뉴스에서 파생된 추가 연구 항목은 없습니다", text)
        self.assertIn("[Research Mission]", text)
        self.assertIn("promotion-ready: 0/3", text)
        self.assertIn(f"active candidate: {candidate.candidate_id}", text)
        self.assertIn("research status: 진행 중", text)
        self.assertIn("next research action:", text)
        self.assertNotIn("추가로 필요한 연구가 없습니다", text)

    def test_pre_market_briefing_shows_awaiting_approval_state(self) -> None:
        from gaon.knowledge.research_mission import (
            add_candidate,
            extract_or_update_mission,
            next_candidate_sequence,
            record_promotion_candidate,
        )
        from gaon.knowledge.strategy_candidate import new_candidate

        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요",
            existing=None,
            now="2026-08-22T00:00:05Z",
        )
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now="2026-08-22T00:00:05Z")
        mission = add_candidate(mission, candidate, now="2026-08-22T00:00:05Z")
        for index in range(3):
            mission = record_promotion_candidate(
                mission,
                strategy_fingerprint=f"verified-distinct-fingerprint-{index}",
                candidate_id=f"KR-ST-00{index + 1}",
                now="2026-08-22T00:00:05Z",
            )
        text = render_pre_market_briefing_ko(
            compose_pre_market_briefing(generated_at="2026-08-22T00:00:05Z", market="KOSPI", research_mission=mission)
        )
        self.assertIn("promotion-ready: 3/3", text)
        self.assertIn("research status: 승격 승인 대기", text)
        self.assertIn("next research action: 사용자 승격 승인 대기", text)

    def test_latest_research_mission_read_model_survives_restart(self) -> None:
        import json

        from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, next_candidate_sequence
        from gaon.knowledge.strategy_candidate import new_candidate

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요",
            existing=None,
            now="2026-08-22T00:00:05Z",
        )
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now="2026-08-22T00:00:05Z")
        mission = add_candidate(mission, candidate, now="2026-08-22T00:00:05Z")
        connection.execute(
            """
            INSERT INTO conversation_sessions(session_id, user_ref, source, status, created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "telegram:100",
                "telegram:100",
                "telegram",
                "active",
                "2026-08-22T00:00:05Z",
                "2026-08-22T00:00:05Z",
                json.dumps({"conversation_mvp": {"research_mission": mission.to_json()}}, sort_keys=True),
            ),
        )
        connection.commit()
        restored = latest_research_mission_from_connection(connection)
        self.assertIsNotNone(restored)
        text = render_pre_market_briefing_ko(
            compose_pre_market_briefing(generated_at="2026-08-22T00:00:05Z", market="KOSPI", research_mission=restored)
        )
        self.assertIn("promotion-ready: 0/3", text)
        self.assertIn(f"active candidate: {candidate.candidate_id}", text)

    def test_terminal_hold_from_budget_exhaustion_still_surfaces_as_followup(self) -> None:
        decision = _hold_decision()
        self.assertEqual(decision.stop_reason, "research_budget_exhausted")
        briefing = compose_post_market_briefing(
            generated_at="2026-08-16T15:40:00Z",
            market="KOSPI",
            live_feedback_json={},
            research_decisions=(decision,),
        )
        text = render_post_market_briefing_ko(briefing)
        self.assertIn("후속 연구가 필요합니다", text)

    def test_schedule_daily_briefing_jobs_reuses_existing_scheduler(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        try:
            migrate(connection)
            repository = ScheduledJobRepository(connection)
            pre_job, post_job, unresolved_job = schedule_daily_briefing_jobs(
                repository,
                timezone="Asia/Seoul",
                next_pre_market_at="2026-08-17T00:00:00Z",
                next_post_market_at="2026-08-17T06:40:00Z",
                created_at="2026-08-16T00:00:00Z",
            )
            self.assertEqual(repository.get(unresolved_job.job_id).job_id, unresolved_job.job_id)
            self.assertEqual(repository.get(pre_job.job_id).job_id, pre_job.job_id)
            self.assertEqual(repository.get(post_job.job_id).job_id, post_job.job_id)
            self.assertEqual((pre_job.metadata or {}).get("kind"), "daily_briefing")
        finally:
            connection.close()

    def test_release_check_passes(self) -> None:
        payload = production_daily_briefing_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertEqual(payload["jobs_registered"], 3)

    def test_morning_briefing_research_state_consistency_release_check_passes(self) -> None:
        payload = production_morning_briefing_research_state_consistency_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertEqual(payload["news_followup_scope"], "news_only")
        self.assertEqual(payload["promotion_ready_progress"], "0/3")
        self.assertTrue(payload["restart_reads_canonical_mission"])
        self.assertFalse(payload["research_action_executed"])


class SendDailyBriefingTests(unittest.TestCase):
    """Step 3: daily_briefing must reuse the existing Telegram send path
    (gaon.integrations.telegram.runtime/formatter/contracts/client) rather
    than creating a second one."""

    def test_dry_run_never_touches_a_real_client(self) -> None:
        client = DryRunTelegramClient()
        sent = send_daily_briefing(client, "12345", "짧은 브리핑", kind="pre_market", dry_run=True)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].dry_run)
        self.assertEqual(sent[0].chat_id, "12345")

    def test_live_send_uses_the_real_client_send_message(self) -> None:
        client = _FakeTelegramClient()
        sent = send_daily_briefing(client, "12345", "짧은 브리핑", kind="post_market", dry_run=False)
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(client.sent[0], ("12345", "짧은 브리핑"))
        self.assertFalse(sent[0].dry_run)

    def test_long_briefing_reuses_the_existing_chunking_infrastructure(self) -> None:
        long_text = "\n".join(f"- 항목 {i}: 자세한 연구 근거 설명 텍스트입니다." for i in range(400))
        expected_chunks = split_message(long_text)
        self.assertGreater(len(expected_chunks), 1)
        client = _FakeTelegramClient()
        sent = send_daily_briefing(client, "12345", long_text, kind="pre_market", dry_run=False)
        self.assertEqual(len(sent), len(expected_chunks))
        self.assertEqual(len(client.sent), len(expected_chunks))

    def test_correlation_id_identifies_briefing_kind_in_dry_run(self) -> None:
        # In dry-run mode the response is constructed locally (no real
        # client round-trip), so the correlation_id we pass through is
        # exactly what callers see. In a live send, Telegram's own response
        # supplies the correlation_id instead, matching how
        # process_update()'s conversation replies already behave.
        client = DryRunTelegramClient()
        sent = send_daily_briefing(client, "12345", "text", kind="post_market", dry_run=True)
        self.assertIn("daily-briefing:post_market", sent[0].correlation_id)


class _StubAuditRecord:
    def __init__(self, audit_id: str, output: dict) -> None:
        self.audit_id = audit_id
        self.result = {"output": output}


class ComposeUnresolvedResearchReviewTests(unittest.TestCase):
    def test_reads_only_already_persisted_audit_records(self) -> None:
        records = (
            _StubAuditRecord(
                "a1",
                {
                    "symbol": "005930",
                    "autonomous_learning_v2": {
                        "research_director_decision": {
                            "action": "collect_more_evidence",
                            "reason": "evidence too weak",
                            "terminal": False,
                        }
                    },
                },
            ),
            _StubAuditRecord(
                "a2",
                {
                    "symbol": "000660",
                    "autonomous_learning_v2": {
                        "research_director_decision": {"action": "hold", "reason": "budget exhausted", "terminal": True}
                    },
                },
            ),
        )
        review = compose_unresolved_research_review(records)
        self.assertEqual(review["unresolved_count"], 1)
        self.assertEqual(review["unresolved"][0]["symbol"], "005930")

    def test_only_the_most_recent_record_per_symbol_counts(self) -> None:
        records = (
            _StubAuditRecord(
                "a1",
                {
                    "symbol": "005930",
                    "autonomous_learning_v2": {
                        "research_director_decision": {"action": "collect_more_evidence", "reason": "x", "terminal": False}
                    },
                },
            ),
            _StubAuditRecord(
                "a2",
                {
                    "symbol": "005930",
                    "autonomous_learning_v2": {
                        "research_director_decision": {
                            "action": "request_human_promotion_review",
                            "reason": "fully validated",
                            "terminal": True,
                        }
                    },
                },
            ),
        )
        review = compose_unresolved_research_review(records)
        self.assertEqual(review["unresolved_count"], 0)

    def test_no_records_is_honestly_empty(self) -> None:
        review = compose_unresolved_research_review(())
        self.assertEqual(review["unresolved_count"], 0)
        self.assertEqual(render_unresolved_research_review_ko(review, generated_at="2026-08-16T09:00:00Z"), "[가온 미해결 연구 점검 - 2026-08-16T09:00:00Z]\n\n현재 후속 조치가 필요한 연구가 없습니다.")


class DailyBriefingSchedulerTests(unittest.TestCase):
    def _repository(self) -> ScheduledJobRepository:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        return ScheduledJobRepository(connection)

    def _scheduler(self, repository: ScheduledJobRepository, client) -> DailyBriefingScheduler:
        return DailyBriefingScheduler(
            repository,
            client,
            chat_id="12345",
            compose_pre_market=lambda: "pre text",
            compose_post_market=lambda: "post text",
            compose_unresolved_review=lambda: "review text",
            dry_run=True,
        )

    def test_run_due_sends_only_jobs_that_are_actually_due(self) -> None:
        repository = self._repository()
        schedule_daily_briefing_jobs(
            repository,
            next_pre_market_at="2026-08-17T00:00:00Z",
            next_post_market_at="2026-08-17T06:40:00Z",
            created_at="2026-08-16T00:00:00Z",
        )
        scheduler = self._scheduler(repository, DryRunTelegramClient())
        results = scheduler.run_due(now="2026-08-17T00:00:00Z")
        self.assertEqual([r.kind for r in results], ["pre_market"])
        self.assertEqual(results[0].status, "succeeded")

    def test_run_due_twice_in_the_same_tick_is_idempotent(self) -> None:
        repository = self._repository()
        schedule_daily_briefing_jobs(
            repository,
            next_pre_market_at="2026-08-17T00:00:00Z",
            next_post_market_at="2026-08-17T06:40:00Z",
            created_at="2026-08-16T00:00:00Z",
        )
        scheduler = self._scheduler(repository, DryRunTelegramClient())
        first = scheduler.run_due(now="2026-08-17T00:00:00Z")
        second = scheduler.run_due(now="2026-08-17T00:00:00Z")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())

    def test_daily_job_is_rescheduled_for_the_next_day_not_left_disabled(self) -> None:
        repository = self._repository()
        schedule_daily_briefing_jobs(
            repository,
            next_pre_market_at="2026-08-17T00:00:00Z",
            next_post_market_at="2026-08-17T06:40:00Z",
            created_at="2026-08-16T00:00:00Z",
        )
        scheduler = self._scheduler(repository, DryRunTelegramClient())
        results = scheduler.run_due(now="2026-08-17T00:00:00Z")
        next_job = repository.get(results[0].rescheduled_job_id)
        self.assertTrue(next_job.enabled)
        self.assertEqual(next_job.schedule.next_run_at, "2026-08-18T00:00:00Z")

    def test_service_restart_resumes_from_durable_state_without_double_sending(self) -> None:
        repository = self._repository()
        schedule_daily_briefing_jobs(
            repository,
            next_pre_market_at="2026-08-17T00:00:00Z",
            next_post_market_at="2026-08-17T06:40:00Z",
            created_at="2026-08-16T00:00:00Z",
        )
        client = _FakeTelegramClient()
        first_scheduler = DailyBriefingScheduler(
            repository,
            client,
            chat_id="12345",
            compose_pre_market=lambda: "pre text",
            compose_post_market=lambda: "post text",
            compose_unresolved_review=lambda: "review text",
            dry_run=False,
        )
        first_scheduler.run_due(now="2026-08-17T07:00:00Z")
        self.assertEqual(len(client.sent), 3)  # pre + post + unresolved_review all due by then

        # Simulate a process restart: brand new scheduler instance, same
        # durable repository, no in-memory state carried over.
        second_scheduler = DailyBriefingScheduler(
            repository,
            client,
            chat_id="12345",
            compose_pre_market=lambda: "pre text",
            compose_post_market=lambda: "post text",
            compose_unresolved_review=lambda: "review text",
            dry_run=False,
        )
        second_scheduler.run_due(now="2026-08-17T08:00:00Z")
        self.assertEqual(len(client.sent), 3)  # nothing new due yet - no duplicate sends
        second_scheduler.run_due(now="2026-08-18T00:00:00Z")
        self.assertEqual(len(client.sent), 4)  # only pre-market's next occurrence is due

    def test_a_failing_composer_does_not_block_other_due_jobs(self) -> None:
        repository = self._repository()
        schedule_daily_briefing_jobs(
            repository,
            next_pre_market_at="2026-08-17T00:00:00Z",
            next_post_market_at="2026-08-17T00:00:00Z",
            next_unresolved_review_at="2026-08-17T00:00:00Z",
            created_at="2026-08-16T00:00:00Z",
        )

        def _raise() -> str:
            raise RuntimeError("composer failed")

        scheduler = DailyBriefingScheduler(
            repository,
            DryRunTelegramClient(),
            chat_id="12345",
            compose_pre_market=_raise,
            compose_post_market=lambda: "post text",
            compose_unresolved_review=lambda: "review text",
            dry_run=True,
        )
        results = scheduler.run_due(now="2026-08-17T00:00:00Z")
        statuses = {r.kind: r.status for r in results}
        self.assertEqual(statuses["pre_market"], "failed")
        self.assertEqual(statuses["post_market"], "succeeded")
        self.assertEqual(statuses["unresolved_review"], "succeeded")


if __name__ == "__main__":
    unittest.main()
