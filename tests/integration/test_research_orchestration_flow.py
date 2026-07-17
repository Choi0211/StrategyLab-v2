import unittest

from gaon.research import ApprovalDecision, ResearchOrchestrator, ResearchRequest, ResearchRunStatus


class ResearchOrchestrationFlowTest(unittest.TestCase):
    def test_telegram_style_approval_flow(self) -> None:
        orchestrator = ResearchOrchestrator()
        request = ResearchRequest("req-tg", "youngha", "ORB 거래량 필터 연구 계획 만들어줘", "2026-07-17T00:00:00Z")

        proposal, approval, awaiting = orchestrator.propose(request, chat_id="100", approval_token="token-tg", expires_at="2026-07-18T00:00:00Z", nonce="nonce-tg")
        decision = ApprovalDecision(approval.approval_id, proposal.proposal_id, "youngha", "100", "token-tg", True, "2026-07-17T01:00:00Z")
        approved = orchestrator.approve(decision, now="2026-07-17T01:00:00Z")
        running = orchestrator.start(proposal.proposal_id, approval_token="token-tg", actor="youngha", chat_id="100", now="2026-07-17T01:01:00Z")

        self.assertEqual(awaiting.status, ResearchRunStatus.AWAITING_APPROVAL)
        self.assertEqual(approved.status, ResearchRunStatus.APPROVED)
        self.assertEqual(running.status, ResearchRunStatus.RUNNING)
        self.assertTrue(any(event.startswith("approved:") for event in orchestrator.audit_events))


if __name__ == "__main__":
    unittest.main()
