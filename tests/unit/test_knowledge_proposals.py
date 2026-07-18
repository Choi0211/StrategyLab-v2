import os
import sqlite3
import tempfile
import unittest

from gaon.research.evidence import EvidenceItem, build_evidence_bundle, stable_content_hash
from gaon.research.knowledge import (
    KnowledgeClaim,
    KnowledgeProposalStatus,
    SQLiteKnowledgeProposalRepository,
    build_knowledge_proposal,
    proposal_event,
    proposal_from_bundle,
    record_proposal_metrics,
)
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


class KnowledgeProposalTest(unittest.TestCase):
    def item(self, evidence_id: str = "ev-1", contradiction: bool = False) -> EvidenceItem:
        return EvidenceItem(evidence_id, "ORB", "https://example.com/orb", "ORB volume evidence", "fake", "2026-07-18T00:00:00Z", stable_content_hash("ORB volume evidence"), 1, 1, 0.5, contradiction=contradiction)

    def test_insufficient_evidence_and_hash_stability(self) -> None:
        claim = KnowledgeClaim("claim-1", "ORB needs volume evidence", ())
        first = build_knowledge_proposal("kp-1", (claim,), (), confidence=0.1, provenance={"source": "test"}, created_at="2026-07-18T00:00:00Z", updated_at="2026-07-18T00:00:00Z")
        second = build_knowledge_proposal("kp-1", (claim,), (), confidence=0.1, provenance={"source": "test"}, created_at="2026-07-18T00:00:00Z", updated_at="2026-07-18T00:00:00Z")

        self.assertEqual(first.status, KnowledgeProposalStatus.INSUFFICIENT_EVIDENCE)
        self.assertEqual(first.proposal_hash, second.proposal_hash)

    def test_versioning_contradiction_no_direct_promotion_and_metrics_event(self) -> None:
        bundle = build_evidence_bundle((self.item(contradiction=True),))
        proposal = proposal_from_bundle("kp-2", bundle, claim_statement="ORB needs volume evidence", created_at="2026-07-18T00:00:00Z")
        metrics = MetricsCollector()
        record_proposal_metrics(metrics, proposal)
        event = proposal_event(proposal, occurred_at="2026-07-18T00:00:00Z")

        self.assertEqual(proposal.next_version(updated_at="2026-07-19T00:00:00Z").version, 2)
        self.assertTrue(proposal.contradictions)
        with self.assertRaises(PermissionError):
            proposal.approve_without_workflow()
        self.assertEqual(event.event_type, "KnowledgeProposalCreated")
        self.assertIn("gaon_knowledge_proposals_total", metrics.snapshot().to_text())

    def test_persistence_round_trip_and_migration_from_v5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            repo = SQLiteKnowledgeProposalRepository(store._connection)
            proposal = proposal_from_bundle("kp-3", build_evidence_bundle((self.item(),)), claim_statement="ORB needs evidence", created_at="2026-07-18T00:00:00Z")
            repo.add(proposal)
            self.assertEqual(repo.get("kp-3").proposal_hash, proposal.proposal_hash)
            store.close()

            legacy = os.path.join(tmp, "legacy.sqlite")
            connection = sqlite3.connect(legacy)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (5);
                CREATE TABLE long_term_memory (memory_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, lifecycle TEXT NOT NULL, content TEXT NOT NULL, source_refs_json TEXT NOT NULL, evidence_refs_json TEXT NOT NULL, validation_ref TEXT, conflict_flag INTEGER NOT NULL DEFAULT 0, revalidation_flag INTEGER NOT NULL DEFAULT 0, retention_until TEXT, archived_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                """
            )
            connection.commit()
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_proposals'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
