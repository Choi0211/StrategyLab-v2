import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.research.approval_workflow import ResearchDecision, SQLiteResearchApprovalRepository, approval_event, build_approval_request, decide, record_approval_metrics
from gaon.research.knowledge import KnowledgeClaim, build_knowledge_proposal
from gaon.runtime.cli import main as cli_main
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


class ResearchApprovalWorkflowTest(unittest.TestCase):
    def proposal(self):
        return build_knowledge_proposal(
            "kp-approval",
            (KnowledgeClaim("claim-1", "ORB requires evidence", ("ev-1",)),),
            ("ev-1",),
            confidence=0.5,
            provenance={"source": "test"},
            created_at="2026-07-18T00:00:00Z",
            updated_at="2026-07-18T00:00:00Z",
        )

    def test_stale_modified_proposal_and_idempotent_approval(self) -> None:
        proposal = self.proposal()
        request = build_approval_request(proposal, actor_ref="actor:redacted", created_at="2026-07-18T00:00:00Z")
        modified = proposal.next_version(updated_at="2026-07-19T00:00:00Z")

        with self.assertRaises(PermissionError):
            decide(request, modified, decision=ResearchDecision.APPROVE, reason="ok", decided_at="2026-07-18T01:00:00Z")

        decision = decide(request, proposal, decision=ResearchDecision.APPROVE, reason="reviewed", decided_at="2026-07-18T01:00:00Z")
        store = RuntimeStateStore(":memory:")
        repo = SQLiteResearchApprovalRepository(store._connection)

        self.assertTrue(repo.add_decision(decision))
        self.assertFalse(repo.add_decision(decision))
        self.assertTrue(repo.consume_for_promotion(decision))
        self.assertFalse(repo.consume_for_promotion(decision))
        store.close()

    def test_rejected_proposal_cannot_promote_and_audit_metrics(self) -> None:
        proposal = self.proposal()
        request = build_approval_request(proposal, actor_ref="actor:redacted", created_at="2026-07-18T00:00:00Z")
        decision = decide(request, proposal, decision=ResearchDecision.REJECT, reason="insufficient", decided_at="2026-07-18T01:00:00Z")
        metrics = MetricsCollector()
        record_approval_metrics(metrics, decision)
        event = approval_event(decision)
        store = RuntimeStateStore(":memory:")
        repo = SQLiteResearchApprovalRepository(store._connection)
        repo.add_decision(decision)

        with self.assertRaises(PermissionError):
            repo.consume_for_promotion(decision)
        self.assertEqual(event.event_type, "ResearchApprovalDecisionRecorded")
        self.assertIn("gaon_knowledge_rejections_total", metrics.snapshot().to_text())
        store.close()

    def test_cli_smoke(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["research-proposals-list"]), 0)
            self.assertEqual(cli_main(["research-proposals-show", "kp-1"]), 0)
            self.assertEqual(cli_main(["research-proposals-approve", "kp-1"]), 0)
            self.assertEqual(cli_main(["research-proposals-reject", "kp-1"]), 0)
            self.assertEqual(cli_main(["research-proposals-revise", "kp-1"]), 0)
        self.assertIn("research-proposals", output.getvalue())


if __name__ == "__main__":
    unittest.main()
