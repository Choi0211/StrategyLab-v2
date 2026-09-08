"""Gaon Agent Foundation V2 - evidence ingestion interface (fail closed).

Learning is not the same as accepting something as true. These tests pin the
contract the PR #218 pipeline must honour.
"""

from __future__ import annotations

import unittest

from gaon.runtime.gaon_agent.evidence import (
    Claim,
    EvidenceIngestionError,
    EvidenceRecord,
    NullEvidenceIngestor,
    Observation,
    SourceRef,
    SourceType,
    VerificationState,
)


def _claim(*, reference: str = "https://youtu.be/abc", retrieved_at: str = "2026-09-08T00:00:00Z") -> Claim:
    source = SourceRef(SourceType.VIDEO, reference, retrieved_at, provider="manual-paste")
    observation = Observation(source, excerpt="RSI 30에서 사면 승률 90%", extraction_method="user_transcript")
    return Claim(
        statement="creator claims an RSI<30 entry has a ~90% win rate",
        attributed_to="youtube creator",
        observation=observation,
    )


class EvidenceRecordTests(unittest.TestCase):
    def test_external_claim_is_recorded_as_unverified_not_fact(self) -> None:
        record = EvidenceRecord(claim=_claim())
        self.assertEqual(record.verification_state, VerificationState.UNVERIFIED)
        self.assertFalse(record.is_trusted)

    def test_missing_provenance_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceRecord(claim=_claim(reference="  "))
        with self.assertRaises(ValueError):
            EvidenceRecord(claim=_claim(retrieved_at=""))

    def test_unverified_record_cannot_carry_a_validation_reference(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceRecord(
                claim=_claim(),
                verification_state=VerificationState.UNVERIFIED,
                independent_validation_ref="val-1",
            )

    def test_only_supported_state_is_trusted(self) -> None:
        record = EvidenceRecord(
            claim=_claim(),
            verification_state=VerificationState.SUPPORTED,
            independent_validation_ref="walkforward-run-42",
        )
        self.assertTrue(record.is_trusted)


class NullEvidenceIngestorTests(unittest.TestCase):
    def test_ingestion_is_not_available_yet_and_refuses(self) -> None:
        with self.assertRaises(EvidenceIngestionError):
            NullEvidenceIngestor().ingest(_claim())


if __name__ == "__main__":
    unittest.main()
