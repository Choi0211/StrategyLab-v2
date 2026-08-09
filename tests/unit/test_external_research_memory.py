from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace

from gaon.knowledge.autonomous_knowledge_loop import (
    AutonomousKnowledgeResearchLoop,
    SourceEvidenceInput,
)
from gaon.knowledge.conflicts import ClaimStance
from gaon.knowledge.external_research_memory import (
    ExternalResearchMemoryBlocker,
    ExternalResearchMemoryStatus,
    ExternalResearchMemoryStore,
    external_research_memory_release_check,
)
from gaon.knowledge.provenance import SourceProvenance, SourceType, TrustLevel
from gaon.storage.foundation import GaonStorage


def _source(title: str, locator: str, text: str) -> SourceProvenance:
    return SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title=title,
        locator=locator,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        trust_level=TrustLevel.HIGH,
        author="Researcher",
        publisher="Journal",
        published_at="2026-01-01",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )


def _loop_result():
    support_text = "Breakout filters can improve trend robustness across regimes."
    oppose_text = "Breakout filters can reduce trend robustness across regimes."
    return AutonomousKnowledgeResearchLoop().run(
        topic_key="strategy.breakout.robustness",
        evidence=(
            SourceEvidenceInput(
                _source("Support", "https://example.invalid/support", support_text),
                support_text.encode("utf-8"),
                "text/plain",
                ClaimStance.SUPPORTS,
            ),
            SourceEvidenceInput(
                _source("Oppose", "https://example.invalid/oppose", oppose_text),
                oppose_text.encode("utf-8"),
                "text/plain",
                ClaimStance.OPPOSES,
            ),
        ),
    )


class ExternalResearchMemoryTests(unittest.TestCase):
    def test_append_only_memory_stores_and_retrieves_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalResearchMemoryStore(GaonStorage(tmp))
            result = store.add_loop_result(
                _loop_result(),
                created_at="2026-08-08T00:00:00+00:00",
            )
            records = store.search_by_topic("strategy.breakout.robustness")

        self.assertEqual(ExternalResearchMemoryStatus.STORED, result.status)
        self.assertEqual(1, len(records))
        self.assertEqual(2, len(records[0].claim_ids))
        self.assertEqual(2, len(records[0].source_ids))
        self.assertFalse(records[0].knowledge_validated)
        self.assertFalse(records[0].production_approved)
        self.assertFalse(records[0].policy_applied)

    def test_duplicate_fingerprint_is_reported_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalResearchMemoryStore(GaonStorage(tmp))
            first = store.add_loop_result(_loop_result())
            duplicate = store.add_loop_result(_loop_result())
            records = store.list_records()

        self.assertEqual(ExternalResearchMemoryStatus.STORED, first.status)
        self.assertEqual(ExternalResearchMemoryStatus.DUPLICATE, duplicate.status)
        self.assertEqual(first.record.memory_id, duplicate.duplicate_memory_id)
        self.assertEqual(1, len(records))

    def test_prevalidated_input_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalResearchMemoryStore(GaonStorage(tmp))
            loop = replace(_loop_result(), knowledge_validated=True)
            result = store.add_loop_result(loop)

        self.assertEqual(ExternalResearchMemoryStatus.BLOCKED, result.status)
        self.assertIn(ExternalResearchMemoryBlocker.PREVALIDATED_INPUT, result.blockers)

    def test_release_check_passes(self) -> None:
        payload = external_research_memory_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(1, payload["records"])
        self.assertEqual("duplicate", payload["duplicate"])


if __name__ == "__main__":
    unittest.main()
