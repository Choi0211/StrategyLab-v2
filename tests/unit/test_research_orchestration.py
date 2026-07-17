import unittest

from gaon.research import ApprovalDecision, InMemoryResearchQueue, QueueItem, ResearchOrchestrator, ResearchRequest, ResearchRun, ResearchRunStatus, ResearchTask


class ResearchOrchestrationTest(unittest.TestCase):
    def request(self) -> ResearchRequest:
        return ResearchRequest("req-1", "youngha", "ORB 거래량 필터를 다시 연구해줘", "2026-07-17T00:00:00Z")

    def test_proposal_creation_and_no_running_without_approval(self) -> None:
        orchestrator = ResearchOrchestrator()
        proposal, approval, run = orchestrator.propose(self.request(), chat_id="100", approval_token="token-1", expires_at="2026-07-18T00:00:00Z")

        self.assertTrue(proposal.plan.approval_required)
        self.assertEqual(approval.proposal_id, proposal.proposal_id)
        self.assertEqual(run.status, ResearchRunStatus.AWAITING_APPROVAL)
        with self.assertRaises(PermissionError):
            run.transition(ResearchRunStatus.RUNNING)

    def test_valid_approval_and_start(self) -> None:
        orchestrator = ResearchOrchestrator()
        proposal, approval, _ = orchestrator.propose(self.request(), chat_id="100", approval_token="token-1", expires_at="2026-07-18T00:00:00Z")
        decision = ApprovalDecision(approval.approval_id, proposal.proposal_id, "youngha", "100", "token-1", True, "2026-07-17T01:00:00Z")

        approved = orchestrator.approve(decision, now="2026-07-17T01:00:00Z")
        running = orchestrator.start(proposal.proposal_id, approval_token="token-1")

        self.assertEqual(approved.status, ResearchRunStatus.APPROVED)
        self.assertEqual(running.status, ResearchRunStatus.RUNNING)
        self.assertTrue(orchestrator.audit_events)

    def test_wrong_actor_expired_duplicate_and_terminal_state(self) -> None:
        orchestrator = ResearchOrchestrator()
        proposal, approval, _ = orchestrator.propose(self.request(), chat_id="100", approval_token="token-1", expires_at="2026-07-18T00:00:00Z")

        with self.assertRaises(PermissionError):
            orchestrator.approve(ApprovalDecision(approval.approval_id, proposal.proposal_id, "other", "100", "token-1", True, "2026-07-17T01:00:00Z"), now="2026-07-17T01:00:00Z")
        with self.assertRaises(PermissionError):
            orchestrator.approve(ApprovalDecision(approval.approval_id, proposal.proposal_id, "youngha", "100", "token-1", True, "2026-07-19T01:00:00Z"), now="2026-07-19T01:00:00Z")

        cancelled = orchestrator.cancel(proposal.proposal_id)
        self.assertEqual(cancelled.status, ResearchRunStatus.CANCELLED)
        with self.assertRaises(ValueError):
            cancelled.transition(ResearchRunStatus.RUNNING, approval_token="token-1")

    def test_queue_deduplication_and_retry_limit(self) -> None:
        queue = InMemoryResearchQueue(max_pending=1)
        queue.add(QueueItem(1, "dedupe", ResearchTask("task-1", "plan")))
        with self.assertRaises(ValueError):
            queue.add(QueueItem(1, "dedupe", ResearchTask("task-2", "plan")))
        task = ResearchTask("task-retry", "retry", max_retries=1)
        self.assertEqual(task.retry("first").retry_count, 1)
        self.assertEqual(task.retry("first").retry("second").status.value, "failed")


if __name__ == "__main__":
    unittest.main()
