from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.news_intelligence import NewsImpact, NewsIntelligenceItem
from gaon.research.research_director import ResearchDirector, ResearchDirectorAction, ResearchDirectorState
from gaon.runtime.daily_briefing import (
    compose_post_market_briefing,
    compose_pre_market_briefing,
    production_daily_briefing_release_check,
    render_post_market_briefing_ko,
    render_pre_market_briefing_ko,
    schedule_daily_briefing_jobs,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.scheduled_automation import ScheduledJobRepository


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
        self.assertIn("추가로 필요한 연구가 없습니다", text)

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
            pre_job, post_job = schedule_daily_briefing_jobs(
                repository,
                timezone="Asia/Seoul",
                next_pre_market_at="2026-08-17T00:00:00Z",
                next_post_market_at="2026-08-17T06:40:00Z",
                created_at="2026-08-16T00:00:00Z",
            )
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
        self.assertEqual(payload["jobs_registered"], 2)


if __name__ == "__main__":
    unittest.main()
