from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.autonomous_knowledge_loop import (
    AutonomousKnowledgeResearchLoop,
    KnowledgeResearchLoopBlocker,
    KnowledgeResearchLoopPolicy,
    KnowledgeResearchLoopStatus,
    SourceEvidenceInput,
    autonomous_knowledge_research_loop_release_check,
)
from gaon.knowledge.conflicts import ClaimStance, ConflictStatus
from gaon.knowledge.provenance import SourceProvenance, SourceType, TrustLevel


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


def _evidence() -> tuple[SourceEvidenceInput, SourceEvidenceInput]:
    support_text = "Breakout filters can improve trend robustness across regimes."
    oppose_text = "Breakout filters can reduce trend robustness across regimes."
    return (
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
    )


class AutonomousKnowledgeResearchLoopTests(unittest.TestCase):
    def test_loop_extracts_claims_and_generates_conflict_questions(self) -> None:
        result = AutonomousKnowledgeResearchLoop().run(
            topic_key="strategy.breakout.robustness",
            evidence=_evidence(),
        )

        self.assertEqual(KnowledgeResearchLoopStatus.COMPLETED, result.status)
        self.assertEqual(2, result.processed_sources)
        self.assertEqual(2, len(result.candidates))
        self.assertIsNotNone(result.reevaluation)
        self.assertIsNotNone(result.reevaluation.conflict)
        self.assertEqual(
            ConflictStatus.UNRESOLVED_CONFLICT,
            result.reevaluation.conflict.status,
        )
        self.assertEqual(1, len(result.research_questions))
        self.assertFalse(result.network_used)
        self.assertFalse(result.knowledge_validated)
        self.assertFalse(result.strategy_mutated)
        self.assertFalse(result.order_executed)

    def test_no_evidence_is_blocked(self) -> None:
        result = AutonomousKnowledgeResearchLoop().run(
            topic_key="strategy.breakout.robustness",
            evidence=(),
        )

        self.assertEqual(KnowledgeResearchLoopStatus.BLOCKED, result.status)
        self.assertIn(KnowledgeResearchLoopBlocker.NO_EVIDENCE, result.blockers)

    def test_byte_budget_exceeded_blocks_before_extraction(self) -> None:
        result = AutonomousKnowledgeResearchLoop(
            policy=KnowledgeResearchLoopPolicy(max_total_bytes=8)
        ).run(
            topic_key="strategy.breakout.robustness",
            evidence=_evidence(),
        )

        self.assertEqual(KnowledgeResearchLoopStatus.BLOCKED, result.status)
        self.assertIn(
            KnowledgeResearchLoopBlocker.BYTE_BUDGET_EXCEEDED,
            result.blockers,
        )
        self.assertEqual((), result.bridge_results)

    def test_unsupported_content_blocks_claim_extraction(self) -> None:
        text = "PDF bytes are not safely text-extracted in this sprint."
        item = SourceEvidenceInput(
            _source("PDF", "https://example.invalid/pdf", text),
            text.encode("utf-8"),
            "application/pdf",
            ClaimStance.SUPPORTS,
        )

        result = AutonomousKnowledgeResearchLoop().run(
            topic_key="strategy.breakout.robustness",
            evidence=(item,),
        )

        self.assertEqual(KnowledgeResearchLoopStatus.BLOCKED, result.status)
        self.assertIn(
            KnowledgeResearchLoopBlocker.CLAIM_EXTRACTION_BLOCKED,
            result.blockers,
        )

    def test_release_check_passes(self) -> None:
        payload = autonomous_knowledge_research_loop_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(2, payload["processed_sources"])
        self.assertEqual(2, payload["claims"])


if __name__ == "__main__":
    unittest.main()
