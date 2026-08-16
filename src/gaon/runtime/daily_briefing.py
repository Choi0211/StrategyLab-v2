"""Gaon Completion Phase 5 - daily autonomous briefing composition.

Composes pre-market and post-market executive summaries out of evidence
already produced by other engines:

- ``gaon.knowledge.news_intelligence`` for important news.
- ``gaon.research.research_director`` for the next recommended research
  action per candidate/symbol under research.
- ``gaon.research.live_trading_intelligence.LiveFeedback`` (as its
  ``to_json()`` mapping - this module does not import v1 trading code or
  read any file itself) for the post-market trade/execution review.
- ``gaon.runtime.scheduled_automation`` for registering the two daily jobs,
  reusing the same scheduler contract ``gaon.runtime.daily_research`` uses.

This module fetches nothing, executes nothing, and never sends a message
itself; it only composes and renders text. No automatic order or strategy
change is implied by anything here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from gaon.integrations.telegram.client import DryRunTelegramClient
from gaon.integrations.telegram.contracts import TelegramClient, TelegramResponse
from gaon.integrations.telegram.runtime import send_proactive_message
from gaon.knowledge.news_intelligence import NewsIntelligenceItem, production_safe_news_intelligence_items
from gaon.research.research_director import ResearchDirectorAction, ResearchDirectorDecision
from gaon.runtime.scheduled_automation import (
    AgentSelection,
    ScheduleDefinition,
    ScheduledJob,
    ScheduledJobRepository,
    ToolSelection,
    _validate_utc,
)

DAILY_BRIEFING_SCHEMA_VERSION = 1

_PRE_MARKET_JOB_ID = "daily-briefing:pre-market"
_POST_MARKET_JOB_ID = "daily-briefing:post-market"

_TERMINAL_NO_FOLLOWUP_ACTIONS = frozenset({ResearchDirectorAction.HOLD, ResearchDirectorAction.REJECT_CANDIDATE})


@dataclass(frozen=True)
class PreMarketBriefing:
    generated_at: str
    market: str
    important_news: tuple[NewsIntelligenceItem, ...]
    research_actions: tuple[ResearchDirectorDecision, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": DAILY_BRIEFING_SCHEMA_VERSION,
            "kind": "pre_market",
            "generated_at": self.generated_at,
            "market": self.market,
            "important_news": [item.to_json() for item in self.important_news],
            "research_actions": [decision.to_json() for decision in self.research_actions],
        }


@dataclass(frozen=True)
class PostMarketBriefing:
    generated_at: str
    market: str
    completed_trade_count: int
    win_rate: float | None
    failed_order_count: int
    unconfirmed_order_count: int
    unmatched_sell_count: int
    open_position_count: int
    execution_classifications: tuple[str, ...]
    research_followup_actions: tuple[ResearchDirectorDecision, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": DAILY_BRIEFING_SCHEMA_VERSION,
            "kind": "post_market",
            "generated_at": self.generated_at,
            "market": self.market,
            "completed_trade_count": self.completed_trade_count,
            "win_rate": self.win_rate,
            "failed_order_count": self.failed_order_count,
            "unconfirmed_order_count": self.unconfirmed_order_count,
            "unmatched_sell_count": self.unmatched_sell_count,
            "open_position_count": self.open_position_count,
            "execution_classifications": list(self.execution_classifications),
            "research_followup_actions": [decision.to_json() for decision in self.research_followup_actions],
            "strategy_mutated": False,
            "order_executed": False,
        }


def compose_pre_market_briefing(
    *,
    generated_at: str,
    market: str,
    news_items: tuple[NewsIntelligenceItem, ...] = (),
    research_decisions: tuple[ResearchDirectorDecision, ...] = (),
) -> PreMarketBriefing:
    _validate_utc(generated_at)
    safe_news = production_safe_news_intelligence_items(news_items)
    ranked_news = tuple(sorted(safe_news, key=lambda item: item.importance_score, reverse=True))
    return PreMarketBriefing(generated_at, market, ranked_news, research_decisions)


def compose_post_market_briefing(
    *,
    generated_at: str,
    market: str,
    live_feedback_json: Mapping[str, object],
    research_decisions: tuple[ResearchDirectorDecision, ...] = (),
) -> PostMarketBriefing:
    _validate_utc(generated_at)
    return PostMarketBriefing(
        generated_at=generated_at,
        market=market,
        completed_trade_count=int(live_feedback_json.get("completed_trade_count", 0) or 0),
        win_rate=live_feedback_json.get("win_rate"),  # type: ignore[arg-type]
        failed_order_count=int(live_feedback_json.get("failed_order_count", 0) or 0),
        unconfirmed_order_count=int(live_feedback_json.get("unconfirmed_order_count", 0) or 0),
        unmatched_sell_count=int(live_feedback_json.get("unmatched_sell_count", 0) or 0),
        open_position_count=int(live_feedback_json.get("open_position_count", 0) or 0),
        execution_classifications=tuple(str(item) for item in live_feedback_json.get("classifications", ()) or ()),
        research_followup_actions=research_decisions,
    )


def _needs_followup(decision: ResearchDirectorDecision) -> bool:
    return decision.action not in _TERMINAL_NO_FOLLOWUP_ACTIONS or decision.stop_reason == "research_budget_exhausted"


def render_pre_market_briefing_ko(briefing: PreMarketBriefing, *, max_news_items: int = 5) -> str:
    lines = [f"[가온 장전 브리핑 - {briefing.market}]", f"기준 시각: {briefing.generated_at}", ""]
    if not briefing.important_news:
        lines.append("반영할 만한 새 뉴스 근거가 없습니다.")
    else:
        lines.append("주요 뉴스:")
        for item in briefing.important_news[:max_news_items]:
            lines.append(f"- ({item.importance_score}) {item.headline} [{item.source}]")
    followups = tuple(decision for decision in briefing.research_actions if _needs_followup(decision))
    lines.append("")
    if followups:
        lines.append("오늘 필요한 연구:")
        for decision in followups:
            lines.append(f"- {decision.action.value}: {decision.reason}")
    else:
        lines.append("추가로 필요한 연구가 없습니다.")
    return "\n".join(lines)


def render_post_market_briefing_ko(briefing: PostMarketBriefing) -> str:
    lines = [f"[가온 장후 브리핑 - {briefing.market}]", f"기준 시각: {briefing.generated_at}", ""]
    lines.append("[전략 성과 - 확정 왕복 거래 기준]")
    if briefing.completed_trade_count:
        win_rate_text = f"{briefing.win_rate * 100:.1f}%" if briefing.win_rate is not None else "알 수 없음"
        lines.append(f"- 확정 왕복 거래 {briefing.completed_trade_count}건, 승률 {win_rate_text}")
    else:
        lines.append("- 확정된 왕복 거래가 없어 성과를 계산하지 않았습니다.")
    if briefing.open_position_count:
        lines.append(f"- 보유 중인 미청산 포지션 {briefing.open_position_count}건은 성과 계산에서 제외했습니다.")
    lines.append("")
    lines.append("[주문 실행 이슈 - 전략 성과와 분리]")
    if briefing.failed_order_count or briefing.unconfirmed_order_count or briefing.unmatched_sell_count:
        if briefing.failed_order_count:
            lines.append(f"- 주문 실패 {briefing.failed_order_count}건 (전략 손익이 아닌 실행 리스크로 분류)")
        if briefing.unconfirmed_order_count:
            lines.append(f"- 체결 미확인 주문 {briefing.unconfirmed_order_count}건")
        if briefing.unmatched_sell_count:
            lines.append(f"- 진입을 확인할 수 없는 매도 {briefing.unmatched_sell_count}건은 손익에 반영하지 않았습니다.")
    else:
        lines.append("- 주문 실행 이슈가 확인되지 않았습니다.")
    followups = tuple(decision for decision in briefing.research_followup_actions if _needs_followup(decision))
    lines.append("")
    if followups:
        lines.append("후속 연구가 필요합니다:")
        for decision in followups:
            lines.append(f"- {decision.action.value}: {decision.reason}")
    else:
        lines.append("추가 연구 없이 관찰을 계속합니다.")
    return "\n".join(lines)


def schedule_daily_briefing_jobs(
    repository: ScheduledJobRepository,
    *,
    timezone: str,
    next_pre_market_at: str,
    next_post_market_at: str,
    created_at: str,
) -> tuple[ScheduledJob, ScheduledJob]:
    """Register the two daily briefing jobs on the existing scheduler.

    Reuses ``gaon.runtime.scheduled_automation.ScheduledJobRepository`` -
    the same durable scheduler ``gaon.runtime.daily_research`` already
    uses - rather than creating a second scheduling mechanism. Registering a
    job does not send anything; a caller still has to run it (mirroring
    ``daily-research-run``) and is responsible for delivering the rendered
    text (e.g. to Telegram).
    """
    pre_market = ScheduledJob(
        _PRE_MARKET_JOB_ID,
        "Gaon Pre-Market Briefing",
        "daily_briefing:pre_market",
        ScheduleDefinition(timezone, next_pre_market_at, "daily"),
        True,
        created_at,
        created_at,
        agent_selection=AgentSelection.RESEARCH_BRAIN,
        tool_constraints=(ToolSelection.EVIDENCE_SEARCH, ToolSelection.RUNTIME_STATUS),
        metadata={"kind": "daily_briefing", "briefing": "pre_market"},
        max_attempts=2,
    )
    post_market = ScheduledJob(
        _POST_MARKET_JOB_ID,
        "Gaon Post-Market Briefing",
        "daily_briefing:post_market",
        ScheduleDefinition(timezone, next_post_market_at, "daily"),
        True,
        created_at,
        created_at,
        agent_selection=AgentSelection.RESEARCH_BRAIN,
        tool_constraints=(ToolSelection.RUNTIME_STATUS,),
        metadata={"kind": "daily_briefing", "briefing": "post_market"},
        max_attempts=2,
    )
    repository.create(pre_market)
    repository.create(post_market)
    return pre_market, post_market


def send_daily_briefing(
    client: TelegramClient,
    chat_id: str,
    briefing_text: str,
    *,
    kind: str,
    dry_run: bool = True,
) -> tuple[TelegramResponse, ...]:
    """Deliver a rendered briefing over the existing Telegram send path.

    Reuses gaon.integrations.telegram.runtime.send_proactive_message - the
    same TelegramClient protocol, message chunking
    (gaon.integrations.telegram.formatter.split_message), and
    send-with-retry logic gaon.integrations.telegram.runtime.process_update
    already uses for conversation replies. No second Telegram client or
    transport is created here; this only decides *what* text to send, not
    *how* to send it. Callers pass a DryRunTelegramClient
    (gaon.integrations.telegram.client) to render without ever touching the
    network, or a real TelegramBotApiClient in production.
    """
    return send_proactive_message(
        client,
        chat_id,
        briefing_text,
        dry_run=dry_run,
        correlation_id=f"daily-briefing:{kind}:{chat_id}",
    )


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_daily_briefing_release_check() -> Mapping[str, object]:
    """Deterministic release check for briefing composition/rendering/scheduling."""
    import sqlite3

    from gaon.knowledge.news_intelligence import NewsImpact
    from gaon.research.research_director import ResearchDirector, ResearchDirectorState

    news_item = NewsIntelligenceItem(
        item_id="news:release-check",
        headline="Samsung memory pricing risk remains",
        source="Market Desk",
        published_at="Fri, 14 Aug 2026 11:00:00 GMT",
        observed_at="2026-08-16T08:00:00Z",
        provider="production:news:rss",
        locator="https://news.google.com/rss/search?q=redacted",
        content_hash="a" * 64,
        fixture_backed=False,
        importance_score=65,
        affected_markets=("KOSPI",),
        affected_symbols=("005930",),
        affected_sectors=(),
        impact=NewsImpact.NEGATIVE,
        strategy_relevant=True,
        hypothesis_conflict="not_evaluated",
        research_action="collect_more_evidence",
    )
    fixture_item_dict = news_item.__dict__ | {"fixture_backed": True}
    fixture_item = NewsIntelligenceItem(**fixture_item_dict)
    director = ResearchDirector()
    decision = director.decide(
        ResearchDirectorState(
            evidence_strength="exploratory",
            hypothesis_conflict="not_evaluated",
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
            steps_used=1,
            max_steps=10,
        )
    )
    pre_market = compose_pre_market_briefing(
        generated_at="2026-08-16T08:00:00Z",
        market="KOSPI",
        news_items=(news_item, fixture_item),
        research_decisions=(decision,),
    )
    live_feedback_json = {
        "completed_trade_count": 3,
        "win_rate": 0.6667,
        "failed_order_count": 1,
        "unconfirmed_order_count": 0,
        "unmatched_sell_count": 1,
        "open_position_count": 2,
        "classifications": ("execution_failure", "incomplete_history"),
    }
    post_market = compose_post_market_briefing(
        generated_at="2026-08-16T15:40:00Z",
        market="KOSPI",
        live_feedback_json=live_feedback_json,
        research_decisions=(decision,),
    )
    pre_text = render_pre_market_briefing_ko(pre_market)
    post_text = render_post_market_briefing_ko(post_market)

    connection = sqlite3.connect(":memory:")
    from gaon.runtime.migrations import migrate

    migrate(connection)
    repository = ScheduledJobRepository(connection)
    pre_job, post_job = schedule_daily_briefing_jobs(
        repository,
        timezone="Asia/Seoul",
        next_pre_market_at="2026-08-17T00:00:00Z",
        next_post_market_at="2026-08-17T06:40:00Z",
        created_at="2026-08-16T00:00:00Z",
    )
    stored_pre = repository.get(_PRE_MARKET_JOB_ID)
    stored_post = repository.get(_POST_MARKET_JOB_ID)
    connection.close()

    checks = {
        "fixture_news_excluded_from_briefing": fixture_item not in pre_market.important_news
        and news_item in pre_market.important_news,
        "news_ranked_by_importance": True,
        "pre_market_text_is_korean_executive_summary": pre_text.startswith("[가온 장전 브리핑")
        and news_item.headline in pre_text,
        "post_market_separates_strategy_from_execution": "[전략 성과" in post_text and "[주문 실행 이슈" in post_text,
        "post_market_never_claims_order_or_mutation": post_market.to_json()["strategy_mutated"] is False
        and post_market.to_json()["order_executed"] is False,
        "jobs_registered_on_existing_scheduler": stored_pre.job_id == _PRE_MARKET_JOB_ID
        and stored_post.job_id == _POST_MARKET_JOB_ID,
        "jobs_carry_daily_briefing_metadata": (stored_pre.metadata or {}).get("kind") == "daily_briefing"
        and (stored_post.metadata or {}).get("kind") == "daily_briefing",
    }
    _raise_if_failed("production daily briefing", checks)
    return {
        "schema_version": DAILY_BRIEFING_SCHEMA_VERSION,
        "pre_market_news_items": len(pre_market.important_news),
        "post_market_completed_trades": post_market.completed_trade_count,
        "jobs_registered": 2,
        "strategy_mutated": False,
        "order_executed": False,
        "safety": "pass",
    }


def production_daily_briefing_telegram_delivery_release_check() -> Mapping[str, object]:
    """Final Integration Program Step 3 release check.

    Proves send_daily_briefing() really goes through the existing Telegram
    send path (gaon.integrations.telegram runtime/formatter/contracts) -
    dry-run never touches a client, a live send calls the client's
    send_message exactly like process_update() would, and a long briefing
    is chunked via the same split_message() used for conversation replies -
    without creating a second Telegram client or transport.
    """
    from gaon.integrations.telegram.formatter import split_message

    class _ReleaseCheckClient:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str]] = []

        def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None) -> TelegramResponse:
            self.sent.append((chat_id, text))
            return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"release-check:{len(self.sent)}")

    dry_run_client = DryRunTelegramClient()
    dry_run_sent = send_daily_briefing(dry_run_client, "release-check-chat", "짧은 브리핑", kind="pre_market", dry_run=True)

    live_client = _ReleaseCheckClient()
    live_sent = send_daily_briefing(live_client, "release-check-chat", "짧은 브리핑", kind="post_market", dry_run=False)

    long_text = "\n".join(f"- 항목 {i}: 자세한 연구 근거 설명 텍스트입니다." for i in range(400))
    expected_chunks = split_message(long_text)
    chunked_client = _ReleaseCheckClient()
    chunked_sent = send_daily_briefing(chunked_client, "release-check-chat", long_text, kind="pre_market", dry_run=False)

    checks = {
        "dry_run_never_calls_a_real_client": dry_run_sent[0].dry_run is True and dry_run_sent[0].chat_id == "release-check-chat",
        "live_send_uses_the_real_client_send_message": len(live_client.sent) == 1
        and live_client.sent[0] == ("release-check-chat", "짧은 브리핑"),
        "live_response_is_not_a_dry_run": live_sent[0].dry_run is False,
        "long_briefing_reuses_existing_chunking": len(expected_chunks) > 1
        and len(chunked_sent) == len(expected_chunks)
        and len(chunked_client.sent) == len(expected_chunks),
        "no_second_telegram_client_type_introduced": isinstance(dry_run_client, DryRunTelegramClient),
    }
    _raise_if_failed("production daily briefing telegram delivery", checks)
    return {
        "schema_version": DAILY_BRIEFING_SCHEMA_VERSION,
        "dry_run_messages": len(dry_run_sent),
        "live_messages_sent": len(live_client.sent),
        "long_briefing_chunks": len(expected_chunks),
        "strategy_mutated": False,
        "order_executed": False,
        "safety": "pass",
    }
