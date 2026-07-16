"""Dry-run Notion client."""

from __future__ import annotations

from gaon.integrations.notion.contracts import NotionPagePayload, SyncResult


class DryRunNotionClient:
    def create_page(self, payload: NotionPagePayload) -> SyncResult:
        return SyncResult(payload.idempotency_key, success=True, dry_run=True)

    def update_page(self, page_id: str, payload: NotionPagePayload) -> SyncResult:
        return SyncResult(payload.idempotency_key, success=True, dry_run=True)

    def archive_page(self, page_id: str) -> SyncResult:
        return SyncResult(page_id, success=False, dry_run=True, error="archive requires explicit approval")

    def query_database(self, database_id: str, query: dict) -> tuple[NotionPagePayload, ...]:
        return ()

    def upsert_research(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)

    def upsert_learning_memory(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)

    def upsert_daily_report(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)

    def upsert_weekly_review(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)

    def upsert_conflict_review(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)

    def upsert_approval_item(self, payload: NotionPagePayload) -> SyncResult:
        return self.create_page(payload)
