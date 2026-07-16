"""Notion contracts without network dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotionPagePayload:
    idempotency_key: str
    page_type: str
    title: str
    properties: dict[str, str]
    blocks: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncResult:
    idempotency_key: str
    success: bool
    dry_run: bool
    retryable: bool = False
    error: str | None = None


class NotionClient(Protocol):
    def create_page(self, payload: NotionPagePayload) -> SyncResult: ...
    def update_page(self, page_id: str, payload: NotionPagePayload) -> SyncResult: ...
    def archive_page(self, page_id: str) -> SyncResult: ...
    def query_database(self, database_id: str, query: dict) -> tuple[NotionPagePayload, ...]: ...
    def upsert_research(self, payload: NotionPagePayload) -> SyncResult: ...
    def upsert_learning_memory(self, payload: NotionPagePayload) -> SyncResult: ...
    def upsert_daily_report(self, payload: NotionPagePayload) -> SyncResult: ...
    def upsert_weekly_review(self, payload: NotionPagePayload) -> SyncResult: ...
    def upsert_conflict_review(self, payload: NotionPagePayload) -> SyncResult: ...
    def upsert_approval_item(self, payload: NotionPagePayload) -> SyncResult: ...
