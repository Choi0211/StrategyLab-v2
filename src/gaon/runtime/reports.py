"""Daily and weekly report contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DailyReport:
    report_id: str
    report_date: str
    generated_at: str
    timezone: str
    research_started: int
    research_completed: int
    research_failed: int
    learning_proposals: int
    duplicates: int
    conflicts: int
    revalidation_due: int
    approvals_pending: int
    top_related_memories: tuple[str, ...]
    recommended_next_actions: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_text(self) -> str:
        return "\n".join((f"Daily Report {self.report_date}", *self.recommended_next_actions, *self.warnings))

    def to_telegram(self) -> str:
        return self.to_text()

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass(frozen=True)
class WeeklyReview:
    review_id: str
    week_start: str
    week_end: str
    generated_at: str
    completed_research: int
    failed_research: int
    success_patterns: tuple[str, ...]
    failure_patterns: tuple[str, ...]
    duplicate_candidates: int
    conflict_candidates: int
    revalidation_summary: str
    confidence_changes: tuple[str, ...]
    notable_learning: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    next_week_priorities: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_text(self) -> str:
        if not self.notable_learning and not self.next_week_priorities:
            return f"Weekly Review {self.week_start} - {self.week_end}\n데이터 부족"
        return "\n".join((f"Weekly Review {self.week_start} - {self.week_end}", *self.next_week_priorities))

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def build_daily_report(report_date: str, generated_at: str, timezone: str = "Asia/Seoul") -> DailyReport:
    return DailyReport(
        report_id=f"daily:{report_date}",
        report_date=report_date,
        generated_at=generated_at,
        timezone=timezone,
        research_started=0,
        research_completed=0,
        research_failed=0,
        learning_proposals=0,
        duplicates=0,
        conflicts=0,
        revalidation_due=0,
        approvals_pending=0,
        top_related_memories=(),
        recommended_next_actions=("검증 대기 항목을 확인하세요.",),
        warnings=(),
        evidence_refs=(),
    )


def build_weekly_review(week_start: str, week_end: str, generated_at: str) -> WeeklyReview:
    return WeeklyReview(
        review_id=f"weekly:{week_start}",
        week_start=week_start,
        week_end=week_end,
        generated_at=generated_at,
        completed_research=0,
        failed_research=0,
        success_patterns=(),
        failure_patterns=(),
        duplicate_candidates=0,
        conflict_candidates=0,
        revalidation_summary="데이터 부족",
        confidence_changes=(),
        notable_learning=(),
        unresolved_items=("데이터 부족",),
        next_week_priorities=(),
        evidence_refs=(),
    )
