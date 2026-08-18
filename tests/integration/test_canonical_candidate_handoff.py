"""Patch 8.7 - Canonical Breadth Candidate -> Persistent StrategyCandidate
Identity Handoff acceptance test.

Real production defect this reproduces and proves fixed: real VPS Telegram
production acceptance testing showed that once a market-wide Research
Mission's multi-symbol breadth research produced report-local improvement
candidates ("후보 A/B/C" - see
``gaon.research.krx_real_pipeline.ImprovementCandidateGenerator``), asking
Gaon to continue validating "the current active strategy candidate" with a
new, not-yet-used evidence symbol did NOT continue any persisted candidate
at all: it re-ran a fresh 5-symbol breadth validation with no candidate
ID/fingerprint and no evidence accumulation, and the next plain "계속
연구해주세요" then minted a brand new candidate (KR-ST-002) instead of
resuming the one already in progress.

Root cause (see ``gaon.runtime.llm_conversation``'s Patch 8.7 comments
above ``multi_symbol_breadth_request`` and the widened
``robustness_continuation_precedence``): a genuine cross-symbol breadth
request naturally names several real symbols (production's own worked
example, ``gaon.research.multi_symbol.PRODUCTION_MULTI_SYMBOL_REQUEST_
TEXT``, lists five). The mission-routing-precedence hook in
``LLMConversationBrain._try_conversational_mvp`` read those named symbols
as "narrow research down to one explicit symbol" and disqualified the
message from the mission-driven candidate cycle entirely - so the request
executed through the disconnected ``_try_authoritative_research_tool``
route, which never touches ``StrategyCandidateRecord`` bookkeeping. A
second, independent gap: a robustness-continuation-shaped message that also
happened to classify as ``STATUS_QUERY`` (e.g. "...유지한 채..." contains
the bare substring "상태") could only override that misclassification once
the candidate had ALREADY reached ``mission.pending_promotion_symbol`` - a
candidate still in its breadth stage had no override.

This test proves, through the REAL production stack
(TelegramConversationAgent -> LLMConversationBrain -> default_tool_registry
-> multi_symbol_research / telegram_autonomous_learning_payload), mocking
only the true external boundaries - same convention as
``tests/integration/test_persistent_strategy_candidate_continuation.py``:

- an explicit-symbol, "후보 A/B/C"-comparing breadth request still
  establishes ONE canonical, fingerprinted StrategyCandidateRecord
- the report's "후보 A/B/C" rows are presentation-only labels, never a
  second identity
- the exact real production robustness-continuation phrasing continues
  THAT SAME candidate (same ID, same fingerprint) instead of re-running an
  unlinked breadth validation
- a plain generic continuation never rotates away from a candidate with
  pending robustness work
- a pure status query never executes a research tool
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import MissionUniverseScope, candidate_records
from gaon.research.multi_symbol import PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import (
    _DeterministicKRUniverseProvider,
    _RecordingTelegramClient,
    _baseline,
    _config,
    _update,
)

_TURN2_REAL_PRODUCTION_MESSAGE = (
    "현재 active strategy candidate의 검증을 계속해주세요. "
    "동일한 candidate ID와 strategy fingerprint를 유지하면서, "
    "아직 강건성 검증에 사용하지 않은 다른 국내 종목을 evidence sample로 "
    "선택해서 검증해주세요. 이전 종목의 검증 상태를 유지한 채 새 evidence를 누적해주세요."
)


class CanonicalCandidateHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str) -> str:
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-18T00:{update_id:02d}:00Z"
        with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
            "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
            return_value={"state": "content_unavailable"},
        ), patch(
            "gaon.research.multi_symbol.build_market_data_provider_from_env",
            return_value=_DeterministicKRUniverseProvider(),
        ):
            result = process_update(
                parse_update_result(_update(update_id, update_id, text), received_at=received_at),
                self.runtime,
                self.client,
            )
        self.assertEqual(result.status, "sent", f"turn {update_id} failed: {result}")
        return self.client.sent[-1][1]

    def _mission(self):
        return self.agent._brain._mission_for("telegram:100")

    def _audits(self, tool_name: str):
        return self.store.tool_audit.list(tool_name=tool_name)

    def test_explicit_symbol_breadth_request_establishes_persisted_candidate(self) -> None:
        # Turn 1: the exact production-shaped breadth request - names five
        # explicit tickers AND asks to compare "후보 A/B/C".
        turn1 = self._send(1, PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)
        self.assertIn("후보 A", turn1)

        mission = self._mission()
        self.assertIsNotNone(mission)
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        candidates = candidate_records(mission)
        self.assertEqual(len(candidates), 1, "the report's 후보 A/B/C rows must not become separate persisted identities")
        candidate_before = candidates[0]
        self.assertRegex(candidate_before.candidate_id, r"^KR-ST-\d{3}$")
        self.assertTrue(candidate_before.strategy_fingerprint)
        self.assertIn(f"[전략 후보 {candidate_before.candidate_id}]", turn1)
        self.assertIn("fingerprint:", turn1)

        # Turn 2: the exact real production robustness-continuation
        # phrasing must continue THIS SAME candidate.
        turn2 = self._send(2, _TURN2_REAL_PRODUCTION_MESSAGE)
        self.assertIn(f"[전략 후보 {candidate_before.candidate_id}]", turn2)
        self.assertIn(candidate_before.strategy_fingerprint[:16], turn2)

        mission = self._mission()
        candidates_after = candidate_records(mission)
        self.assertEqual(len(candidates_after), 1)
        candidate_after = candidates_after[0]
        self.assertEqual(candidate_after.candidate_id, candidate_before.candidate_id)
        self.assertEqual(candidate_after.strategy_fingerprint, candidate_before.strategy_fingerprint)

        # Turn 3: a plain generic continuation must not rotate away from
        # the candidate while robustness work is pending.
        self._send(3, "계속 연구해주세요")
        mission = self._mission()
        candidates_turn3 = candidate_records(mission)
        self.assertEqual(len(candidates_turn3), 1, "계속 연구해주세요 must not mint a second candidate while robustness work is pending")
        self.assertEqual(candidates_turn3[0].candidate_id, candidate_before.candidate_id)
        self.assertEqual(candidates_turn3[0].strategy_fingerprint, candidate_before.strategy_fingerprint)

        # Bounded execution: exactly one research tool call per turn.
        self.assertLessEqual(len(self._audits("multi_symbol_research")) + len(self._audits("autonomous_learning_research")), 3)

    def test_status_query_after_handoff_is_read_only(self) -> None:
        self._send(1, PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)
        candidate_before = candidate_records(self._mission())[0]
        before_multi = len(self._audits("multi_symbol_research"))
        before_robust = len(self._audits("autonomous_learning_research"))

        status_text = self._send(2, "현재 후보 상태 보여줘")

        self.assertEqual(len(self._audits("multi_symbol_research")), before_multi)
        self.assertEqual(len(self._audits("autonomous_learning_research")), before_robust)
        self.assertIn(candidate_before.candidate_id, status_text)

    def test_ambiguous_candidate_reference_without_a_mission_fails_closed(self) -> None:
        # No prior turn ever established a mission or candidate in this
        # session - "후보 A 계속 검증해줘" alone must never fabricate one.
        self._send(1, "후보 A 계속 검증해줘")
        mission = self._mission()
        candidates = candidate_records(mission) if mission is not None else ()
        self.assertEqual(len(candidates), 0, "an ambiguous candidate reference with no active mission must fail closed, not invent an identity")


if __name__ == "__main__":
    unittest.main()
