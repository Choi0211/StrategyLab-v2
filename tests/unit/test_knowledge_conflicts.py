from __future__ import annotations

import unittest

from gaon.knowledge.claims import (
    KnowledgeCandidate,
    KnowledgeCandidateStatus,
)
from gaon.knowledge.conflicts import (
    ClaimStance,
    ConflictStatus,
    KnowledgeConflictDetector,
    PositionedClaim,
    canonical_conflict_id,
    conflict_release_check,
)
from gaon.knowledge.quality import EvidenceUse


TOPIC = "trend.regime.robustness"


def make_candidate(
    suffix: str,
    *,
    source: str,
    score: int = 80,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        candidate_id=f"knowledge-candidate:{suffix}",
        claim_id=f"claim:{suffix}",
        source_id=f"source:{source}",
        claim_text=f"Claim text {suffix} is sufficiently descriptive.",
        status=KnowledgeCandidateStatus.EVIDENCE_BACKED,
        evidence_use=EvidenceUse.PRIMARY,
        evidence_score=score,
    )


def positioned(
    suffix: str,
    *,
    source: str,
    stance: ClaimStance,
    score: int = 80,
) -> PositionedClaim:
    return PositionedClaim.from_candidate(
        make_candidate(
            suffix,
            source=source,
            score=score,
        ),
        topic_key=TOPIC,
        stance=stance,
    )


class KnowledgeConflictTests(unittest.TestCase):
    def test_conflict_id_is_order_independent(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
        )
        b = positioned(
            "b",
            source="b",
            stance=ClaimStance.OPPOSES,
        )

        first = canonical_conflict_id(
            topic_key=TOPIC,
            claims=(a, b),
        )
        second = canonical_conflict_id(
            topic_key=TOPIC,
            claims=(b, a),
        )

        self.assertEqual(first, second)

    def test_two_independent_supports_are_supported(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
        )
        b = positioned(
            "b",
            source="b",
            stance=ClaimStance.SUPPORTS,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, b),
        )

        self.assertEqual(
            result.status,
            ConflictStatus.SUPPORTED,
        )
        self.assertEqual(result.independent_source_count, 2)
        self.assertFalse(result.knowledge_validated)

    def test_independent_opposition_becomes_unresolved_conflict(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
            score=95,
        )
        b = positioned(
            "b",
            source="b",
            stance=ClaimStance.OPPOSES,
            score=40,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, b),
        )

        self.assertEqual(
            result.status,
            ConflictStatus.UNRESOLVED_CONFLICT,
        )
        self.assertFalse(result.automatic_resolution)

        # Score advantage must not silently resolve contradiction.
        self.assertGreater(
            result.supporting_score,
            result.opposing_score,
        )

    def test_single_source_support_is_not_independent_validation(self) -> None:
        a = positioned(
            "a",
            source="same",
            stance=ClaimStance.SUPPORTS,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a,),
        )

        self.assertEqual(
            result.status,
            ConflictStatus.INSUFFICIENT_INDEPENDENCE,
        )

    def test_same_source_opposing_claims_are_not_independent(self) -> None:
        a = positioned(
            "a",
            source="same",
            stance=ClaimStance.SUPPORTS,
        )
        b = positioned(
            "b",
            source="same",
            stance=ClaimStance.OPPOSES,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, b),
        )

        self.assertEqual(
            result.status,
            ConflictStatus.INSUFFICIENT_INDEPENDENCE,
        )

    def test_neutral_only_is_not_comparable_evidence(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.NEUTRAL,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a,),
        )

        self.assertEqual(
            result.status,
            ConflictStatus.NO_COMPARABLE_EVIDENCE,
        )

    def test_mixed_topics_are_blocked(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
        )

        b = PositionedClaim.from_candidate(
            make_candidate(
                "b",
                source="b",
            ),
            topic_key="different.topic",
            stance=ClaimStance.SUPPORTS,
        )

        with self.assertRaises(ValueError):
            KnowledgeConflictDetector().evaluate(
                TOPIC,
                (a, b),
            )

    def test_duplicate_claim_does_not_inflate_source_count(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, a),
        )

        self.assertEqual(
            result.independent_source_count,
            1,
        )
        self.assertEqual(
            result.status,
            ConflictStatus.INSUFFICIENT_INDEPENDENCE,
        )

    def test_multiple_claims_same_source_use_strongest_score_once(self) -> None:
        a = positioned(
            "a",
            source="same",
            stance=ClaimStance.SUPPORTS,
            score=40,
        )
        b = positioned(
            "b",
            source="same",
            stance=ClaimStance.SUPPORTS,
            score=90,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, b),
        )

        self.assertEqual(result.supporting_score, 90)

    def test_result_never_auto_validates_or_approves(self) -> None:
        a = positioned(
            "a",
            source="a",
            stance=ClaimStance.SUPPORTS,
        )
        b = positioned(
            "b",
            source="b",
            stance=ClaimStance.SUPPORTS,
        )

        result = KnowledgeConflictDetector().evaluate(
            TOPIC,
            (a, b),
        )

        self.assertFalse(result.knowledge_validated)
        self.assertFalse(result.production_approved)
        self.assertFalse(result.policy_applied)
        self.assertFalse(result.automatic_resolution)

    def test_release_check(self) -> None:
        self.assertEqual(
            conflict_release_check()["safety"],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
