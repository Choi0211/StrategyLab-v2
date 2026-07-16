"""Notion payload mappers."""

from __future__ import annotations

from gaon.integrations.notion.contracts import NotionPagePayload
from gaon.learning.contracts import LearningRecord
from gaon.runtime.reports import DailyReport, WeeklyReview


def learning_memory_payload(record: LearningRecord) -> NotionPagePayload:
    return NotionPagePayload(
        idempotency_key=f"learning:{record.record_id}",
        page_type="learning_memory",
        title=record.content[:80],
        properties={
            "Record ID": record.record_id,
            "Record Type": record.record_type.value,
            "Scope": record.scope,
            "Project": record.project,
            "Strategy": record.strategy,
            "Market": record.market,
            "Confidence": str(record.confidence.value),
            "Evidence Count": str(len(record.evidence)),
            "Revalidation Due": record.revalidation.due_at,
            "Validation State": record.confidence.validation_state,
            "Gaon Entity ID": record.record_id,
        },
    )


def daily_report_payload(report: DailyReport) -> NotionPagePayload:
    return NotionPagePayload(f"daily:{report.report_id}", "daily_report", report.report_id, {"Date": report.report_date}, (report.to_text(),))


def weekly_review_payload(review: WeeklyReview) -> NotionPagePayload:
    return NotionPagePayload(f"weekly:{review.review_id}", "weekly_review", review.review_id, {"Week Start": review.week_start}, (review.to_text(),))
