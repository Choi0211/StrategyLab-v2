"""Golden JSON fixtures for Learning Memory tests."""

from __future__ import annotations

GOLDEN_LEARNING_RECORD_JSON = (
    '{"data": {"audit_ref": "audit-001", "confidence": {"conflict_penalty": 0.0, "evidence_count": 1, '
    '"reason": "fixture confidence", "recency": 1.0, "validation_state": "need_validation", "value": 0.75}, '
    '"content": "ORB needs volume confirmation.", "created_at": "2026-07-17T00:00:00Z", '
    '"evidence": [{"evidence_id": "ev-001", "evidence_type": "research", "reference": "golden-fixture", '
    '"summary": "golden fixture evidence"}], "market": "KRX", "project": "StrategyLab", "record_id": "record-001", '
    '"record_type": "knowledge_claim", "revalidation": {"due_at": "2026-08-01T00:00:00Z", "frequency": "monthly", '
    '"market": "KRX", "project": "StrategyLab", "reason": "scheduled validation", "schedule_id": "rv-001", '
    '"scope": "strategy-research", "status": "pending", "strategy": "ORB", "target_ref": "claim-001"}, '
    '"scope": "strategy-research", "strategy": "ORB", "updated_at": "2026-07-17T00:00:00Z", "version": 1}, '
    '"kind": "learning_record", "schema_version": 1}'
)

MIGRATION_V1_LEARNING_RECORD_JSON = GOLDEN_LEARNING_RECORD_JSON
