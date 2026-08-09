from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from gaon.knowledge.claims import (
    KnowledgeCandidate,
    KnowledgeCandidateBuilder,
    VerbatimClaimExtractor,
)
from gaon.knowledge.conflicts import ClaimStance, ConflictStatus
from gaon.knowledge.evidence_reevaluation import (
    EvidenceConflictReevaluator,
    EvidenceReevaluationBlocker,
    EvidenceReevaluationStatus,
    evidence_conflict_reevaluation_release_check,
)
from gaon.knowledge.provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
)
from gaon.knowledge.quality import SourceQualityEvaluator


def _candidate(title: str, locator: str, text: str) -> KnowledgeCandidate:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source = SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title=title,
        locator=locator,
        content_sha256=digest,
        trust_level=TrustLevel.HIGH,
        author="Researcher",
        publisher="Journal",
        published_at="2026-01-01",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )
    claim = VerbatimClaimExtractor(max_claims=1).extract(source, text)[0]
    assessment = SourceQualityEvaluator().evaluate(source)
    return KnowledgeCandidateBuilder().build(claim, assessment)


class EvidenceConflictReevaluationTests(unittest.TestCase):
    def test_new_opposing_evidence_changes_conflict_status(self) -> None:
        support = _candidate(
            "Support",
            "https://example.invalid/support",
            "Breakout filters can improve robustness across regimes.",
        )
        oppose = _candidate(
            "Oppose",
            "https://example.invalid/oppose",
            "Breakout filters can reduce robustness across regimes.",
        )
        reevaluator = EvidenceConflictReevaluator()

        first = reevaluator.reevaluate(
            topic_key="strategy.breakout.robustness",
            candidates=(support,),
            stances={support.candidate_id: ClaimStance.SUPPORTS},
        )
        second = reevaluator.reevaluate(
            topic_key="strategy.breakout.robustness",
            candidates=(support, oppose),
            stances={
                support.candidate_id: ClaimStance.SUPPORTS,
                oppose.candidate_id: ClaimStance.OPPOSES,
            },
            prior_conflict=first.conflict,
        )

        self.assertIsNotNone(first.conflict)
        self.assertEqual(
            ConflictStatus.INSUFFICIENT_INDEPENDENCE,
            first.conflict.status,
        )
        self.assertIsNotNone(second.conflict)
        self.assertEqual(
            ConflictStatus.UNRESOLVED_CONFLICT,
            second.conflict.status,
        )
        self.assertTrue(second.conflict_status_changed)
        self.assertEqual(1, len(second.research_questions))
        self.assertFalse(second.automatic_resolution)

    def test_missing_stance_blocks_reevaluation(self) -> None:
        support = _candidate(
            "Support",
            "https://example.invalid/support",
            "Breakout filters can improve robustness across regimes.",
        )

        result = EvidenceConflictReevaluator().reevaluate(
            topic_key="strategy.breakout.robustness",
            candidates=(support,),
            stances={},
        )

        self.assertEqual(EvidenceReevaluationStatus.BLOCKED, result.status)
        self.assertIn(EvidenceReevaluationBlocker.MISSING_STANCE, result.blockers)
        self.assertIsNone(result.conflict)
        self.assertEqual((), result.research_questions)

    def test_validated_or_approved_input_is_blocked(self) -> None:
        support = _candidate(
            "Support",
            "https://example.invalid/support",
            "Breakout filters can improve robustness across regimes.",
        )
        validated = replace(support, knowledge_validated=True)

        result = EvidenceConflictReevaluator().reevaluate(
            topic_key="strategy.breakout.robustness",
            candidates=(validated,),
            stances={validated.candidate_id: ClaimStance.SUPPORTS},
        )

        self.assertEqual(EvidenceReevaluationStatus.BLOCKED, result.status)
        self.assertIn(
            EvidenceReevaluationBlocker.VALIDATED_OR_APPROVED_INPUT,
            result.blockers,
        )

    def test_release_check_passes(self) -> None:
        payload = evidence_conflict_reevaluation_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(
            ConflictStatus.UNRESOLVED_CONFLICT.value,
            payload["conflict_status"],
        )


if __name__ == "__main__":
    unittest.main()
