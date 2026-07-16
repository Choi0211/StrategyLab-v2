"""Dry-run Notion sync workflow."""

from __future__ import annotations

from gaon.integrations.notion.client import DryRunNotionClient
from gaon.integrations.notion.contracts import NotionPagePayload, SyncResult


class DryRunNotionSync:
    def __init__(self, client: DryRunNotionClient | None = None) -> None:
        self._client = client or DryRunNotionClient()
        self._seen: set[str] = set()

    def upsert(self, payload: NotionPagePayload) -> SyncResult:
        if payload.idempotency_key in self._seen:
            return SyncResult(payload.idempotency_key, success=True, dry_run=True)
        self._seen.add(payload.idempotency_key)
        return self._client.create_page(payload)
