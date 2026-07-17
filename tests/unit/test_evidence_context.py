import unittest

from gaon.research.evidence import EvidenceItem, build_evidence_bundle, evidence_from_search, stable_content_hash
from gaon.research.search import SearchResult, SourceMetadata


class EvidenceContextTest(unittest.TestCase):
    def result(self, title: str, url: str, content: str) -> SearchResult:
        return SearchResult(title, url, content[:80], content, SourceMetadata(url, "example.com", "2026-07-18T00:00:00Z", "fake"))

    def test_stable_ranking_and_exact_duplicate_removal(self) -> None:
        first = evidence_from_search(self.result("ORB", "https://example.com/a", "ORB breakout volume evidence"), query="ORB volume")
        duplicate = evidence_from_search(self.result("ORB duplicate", "https://example.com/b", "ORB breakout volume evidence"), query="ORB volume")
        other = evidence_from_search(self.result("Other", "https://example.com/c", "unrelated"), query="ORB volume")

        bundle = build_evidence_bundle((other, duplicate, first))

        self.assertEqual(bundle.items[0].content_hash, stable_content_hash("ORB breakout volume evidence"))
        self.assertEqual(len(bundle.items), 2)
        self.assertIn("deduplicated=1", bundle.diagnostics)

    def test_near_duplicate_citation_stability_and_budget(self) -> None:
        item1 = evidence_from_search(self.result("A", "https://example.com/a", "one two three four five six"), query="one")
        item2 = evidence_from_search(self.result("B", "https://example.com/b", "one two three four five six extra"), query="one")

        bundle = build_evidence_bundle((item1, item2), context_budget_chars=20)

        self.assertEqual(bundle.citations[0].citation_id, "C1")
        self.assertTrue(bundle.truncated)
        self.assertIn("context_truncated", bundle.diagnostics)

    def test_memory_external_merge_and_conflict_preservation(self) -> None:
        external = evidence_from_search(self.result("Claim", "https://example.com/a", "ORB works in high volume"), query="ORB")
        memory = EvidenceItem(
            "mem-1",
            "Claim",
            "memory://record-1",
            "ORB fails in low liquidity",
            "memory",
            "2026-07-18T00:00:00Z",
            stable_content_hash("ORB fails in low liquidity"),
            relevance=1.0,
            freshness=1.0,
            source_quality=0.5,
            contradiction=True,
        )

        bundle = build_evidence_bundle((external,), (memory,))

        self.assertEqual(len(bundle.items), 2)
        self.assertTrue(any(item.contradiction for item in bundle.items))
        self.assertIn("contradictions_preserved", bundle.diagnostics)


if __name__ == "__main__":
    unittest.main()
