from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.knowledge.evidence_hypothesis import (
    EvidenceBackedHypothesisGenerator,
    StrategyHypothesisBlocker,
    StrategyHypothesisStatus,
    evidence_backed_hypothesis_release_check,
)
from gaon.knowledge.external_research_memory import ExternalResearchMemoryRecord


def _memory() -> ExternalResearchMemoryRecord:
    return ExternalResearchMemoryRecord(
        memory_id="external-research-memory:test",
        fingerprint="f" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:test",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a", "claim:b"),
        question_ids=("research-question:a",),
        source_ids=("source:a", "source:b"),
        created_at="2026-08-08T00:00:00+00:00",
    )


class EvidenceBackedHypothesisTests(unittest.TestCase):
    def test_memory_backed_hypothesis_is_proposed_not_tested(self) -> None:
        hypothesis = EvidenceBackedHypothesisGenerator().generate(
            topic_key="strategy.breakout.robustness",
            memories=(_memory(),),
            changed_rules=("add regime filter before breakout entries",),
            rationale="Evidence conflict suggests regime context matters.",
            mechanism="Filter entries to the conditions named by evidence.",
            falsification_criteria=("Reject if independent validation does not support it.",),
        )

        self.assertEqual(StrategyHypothesisStatus.PROPOSED, hypothesis.status)
        self.assertEqual(("claim:a", "claim:b"), hypothesis.claim_ids)
        self.assertFalse(hypothesis.tested)
        self.assertFalse(hypothesis.knowledge_validated)
        self.assertFalse(hypothesis.production_approved)
        self.assertFalse(hypothesis.strategy_mutated)
        self.assertFalse(hypothesis.order_executed)

    def test_no_memory_blocks_hypothesis(self) -> None:
        hypothesis = EvidenceBackedHypothesisGenerator().generate(
            topic_key="strategy.breakout.robustness",
            memories=(),
            changed_rules=("add regime filter",),
            rationale="No evidence should block.",
            mechanism="No evidence.",
            falsification_criteria=("Reject without evidence.",),
        )

        self.assertEqual(StrategyHypothesisStatus.BLOCKED, hypothesis.status)
        self.assertIn(StrategyHypothesisBlocker.NO_MEMORY, hypothesis.blockers)

    def test_fabricated_metric_tokens_block_hypothesis(self) -> None:
        hypothesis = EvidenceBackedHypothesisGenerator().generate(
            topic_key="strategy.breakout.robustness",
            memories=(_memory(),),
            changed_rules=("target return=12%",),
            rationale="Invented expected return.",
            mechanism="No tested evidence.",
            falsification_criteria=("Reject if sharpe=1.5 is not achieved.",),
        )

        self.assertEqual(StrategyHypothesisStatus.BLOCKED, hypothesis.status)
        self.assertIn(
            StrategyHypothesisBlocker.FABRICATED_METRIC,
            hypothesis.blockers,
        )

    def test_prevalidated_memory_is_blocked(self) -> None:
        memory = replace(_memory(), knowledge_validated=True)

        hypothesis = EvidenceBackedHypothesisGenerator().generate(
            topic_key="strategy.breakout.robustness",
            memories=(memory,),
            changed_rules=("add regime filter",),
            rationale="Prevalidated memory cannot enter this gate.",
            mechanism="Blocked.",
            falsification_criteria=("Reject until reviewed.",),
        )

        self.assertEqual(StrategyHypothesisStatus.BLOCKED, hypothesis.status)
        self.assertIn(
            StrategyHypothesisBlocker.PREVALIDATED_MEMORY,
            hypothesis.blockers,
        )

    def test_release_check_passes(self) -> None:
        payload = evidence_backed_hypothesis_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual("proposed", payload["status"])
        self.assertEqual(2, payload["claim_refs"])


if __name__ == "__main__":
    unittest.main()
