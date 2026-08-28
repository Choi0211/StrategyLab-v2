"""Patch 8.8 - Canonical Research Mission Read Model & Conversational State
Consistency acceptance test.

Real production defect this reproduces and proves fixed: real VPS Telegram
production acceptance testing (after Patch 8.7 shipped and its own release
check passed) showed a SEPARATE state/routing defect. Once an active,
non-single-symbol Research Mission had a real ``StrategyCandidateRecord`` in
progress (cross-symbol validated evidence and cumulative trades already
accumulated), read-only questions about that candidate had no dedicated
mission-aware route at all:

- "현재 연구 중인 단타 전략과 활성 후보를 설명해주세요" answered from legacy
  V5/Champion pipeline state instead of the canonical Research Mission /
  active StrategyCandidateRecord.
- "현재 활성 후보의 fingerprint와 지금까지 검증한 종목 수, 누적 거래 수를
  알려주세요" - a read-only question - silently executed a brand-new
  Autonomous Learning V2 research cycle and answered from a STALE, unrelated
  single-symbol result.
- "현재 단타 전략은 몇 점 정도인가요?" also re-executed research instead of
  answering the score question from real evidence (or admitting it could
  not).
- "현재 단타 전략을 설명해주세요" answered from a stale single-symbol
  context showing "거래 표본: 0회" / "계산 불가" even though the active
  candidate's own real cumulative evidence was non-zero - a production
  regression from validated_symbols=5/cumulative_trades=25 down to a stale
  0 this test's fixture reproduces at a smaller (but structurally
  identical) scale.

Root cause (see ``gaon.knowledge.research_mission.is_mission_candidate_
read_request`` and ``LLMConversationBrain._render_mission_candidate_read_
response``'s Patch 8.8 comments): none of these messages were ever
recognized as a read-only question about the ACTIVE mission/candidate
itself. Lacking a route, they fell through into legacy/reasoning-followup
machinery keyed off ``ConversationalMVPContext`` - a per-session cache of
the single most recent tool result, entirely independent of the mission's
own persisted candidate progress.

This test proves, through the REAL production stack
(TelegramConversationAgent -> LLMConversationBrain -> default_tool_registry
-> multi_symbol_research / autonomous_learning_research), mocking only the
true external boundaries - same convention as
``tests/integration/test_canonical_candidate_handoff.py``:

- a mission-aware read-only question answers from the active
  StrategyCandidateRecord/ResearchMission, never legacy V5/Champion state
- identity/fingerprint/progress numbers survive verbatim across turns -
  never regressing to a stale or zero value
- the actual mission-driven research continuation still executes and stays
  on the SAME candidate
- a score question never fabricates a numeric score and never re-executes
  research
- "설명해주세요" describes the active candidate's own real rules, never a
  stale single-symbol backtest result
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import candidate_records
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import (
    _DeterministicKRUniverseProvider,
    _RecordingTelegramClient,
    _baseline,
    _config,
    _update,
)

_LEGACY_V5_TOKENS = ("v5-challenger-backtest", "champion_status", "promotion_approval", "챔피언")
_FABRICATED_SCORE_PATTERN = re.compile(r"\b\d{1,3}\s*(점|/\s*100)")


class CanonicalResearchReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str, *, force_hold: bool = False) -> str:
        from contextlib import ExitStack

        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-18T00:{update_id:02d}:00Z"
        with ExitStack() as stack:
            stack.enter_context(patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline))
            stack.enter_context(patch("gaon.knowledge.telegram_autonomous_learning._run_production_external_research", return_value={"state": "content_unavailable"}))
            stack.enter_context(patch("gaon.research.multi_symbol.build_market_data_provider_from_env", return_value=_DeterministicKRUniverseProvider()))
            if force_hold:
                from gaon.research.research_director import ResearchDirectorAction, ResearchDirectorDecision

                forced = ResearchDirectorDecision(ResearchDirectorAction.HOLD, "test-forced-hold", (), True, "test_forced_hold")
                stack.enter_context(patch("gaon.knowledge.telegram_autonomous_learning.decide_next_research_action", return_value=forced))
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

    def _research_tool_call_count(self) -> int:
        return sum(
            len(self._audits(name))
            for name in ("multi_symbol_research", "autonomous_learning_research", "autonomous_research_cycle")
        )

    def test_short_strategy_status_reads_canonical_mission_without_research(self) -> None:
        self._send(20, "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. 현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.")
        self._send(21, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(22, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        self.assertIsNotNone(mission)
        candidate = candidate_records(mission)[0]

        before = self._research_tool_call_count()
        text = self._send(23, "단타전략은 잘 연구되고잇나요?")
        self.assertEqual(self._research_tool_call_count(), before)
        self.assertIn(candidate.candidate_id, text)
        self.assertIn(candidate.strategy_fingerprint[:16], text)
        self.assertNotIn("unknown", text.casefold())

    def test_bounded_multi_faceted_continuation_stays_on_the_same_active_mission(self) -> None:
        self._send(20, "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. 현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.")
        self._send(21, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(22, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission_before = self._mission()
        candidate_before = candidate_records(mission_before)[0]

        before = self._research_tool_call_count()
        self._send(23, "여러방면으로 테스트 및 연구 진행해주세요")
        after_h = self._research_tool_call_count()
        self.assertEqual(after_h, before + 1, "여러방면으로 request must be a single bounded cycle")
        mission_after_h = self._mission()
        self.assertEqual(mission_after_h.mission_id, mission_before.mission_id, "must not create a new unrelated mission")
        self.assertEqual(candidate_records(mission_after_h)[0].candidate_id, candidate_before.candidate_id)

        self._send(24, "연구 계속해주세요")
        after_i = self._research_tool_call_count()
        self.assertEqual(after_i, after_h + 1, "연구 계속해주세요 must also be a single bounded cycle")
        mission_after_i = self._mission()
        self.assertEqual(mission_after_i.mission_id, mission_before.mission_id)
        self.assertEqual(candidate_records(mission_after_i)[0].candidate_id, candidate_before.candidate_id)

    def test_six_turn_production_sequence_never_regresses_candidate_state(self) -> None:
        # ------------------------------------------------------------
        # Turn 1: establish a market-wide ResearchMission with a real
        # active candidate, and (production's actual starting shape) a
        # STALE single-symbol autonomous_learning_v2 conversational
        # context from before the mission broadened.
        # ------------------------------------------------------------
        self._send(1, "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. 현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.")
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        self.assertIsNotNone(mission)
        candidate_before = candidate_records(mission)[0]
        self.assertGreater(candidate_before.valid_symbols, 0)
        self.assertGreater(candidate_before.trade_count, 0)

        # One forced-HOLD robustness cycle establishes non-trivial,
        # canonical cumulative evidence (analogous to the reported
        # production validated_symbols=5/cumulative_trades=25 state) -
        # this is the value every later read-only turn below must never
        # regress below.
        self._send(4, "후보를 유지한 채 강건성 검증을 계속해주세요", force_hold=True)
        mission = self._mission()
        candidate = candidate_records(mission)[0]
        self.assertEqual(candidate.candidate_id, candidate_before.candidate_id)
        baseline_valid_symbols = candidate.valid_symbols
        baseline_trade_count = candidate.trade_count
        self.assertGreater(baseline_valid_symbols, 0)
        self.assertGreater(baseline_trade_count, 0)

        # ------------------------------------------------------------
        # Turn 2: "현재 연구 중인 단타 전략과 활성 후보를 설명해주세요."
        # ------------------------------------------------------------
        before = self._research_tool_call_count()
        turn2 = self._send(5, "현재 연구 중인 단타 전략과 활성 후보를 설명해주세요.")
        after = self._research_tool_call_count()
        self.assertEqual(before, after, "a read-only mission/candidate question must never execute a research tool")
        self.assertIn(candidate.candidate_id, turn2)
        self.assertIn(candidate.strategy_fingerprint[:16], turn2)
        for token in _LEGACY_V5_TOKENS:
            self.assertNotIn(token, turn2, f"legacy V5/Champion state must not be returned as the current candidate ({token!r} found)")

        # ------------------------------------------------------------
        # Turn 3: "현재 활성 후보의 fingerprint와 지금까지 검증한 종목 수,
        # 누적 거래 수를 알려주세요."
        # ------------------------------------------------------------
        before = self._research_tool_call_count()
        turn3 = self._send(6, "현재 활성 후보의 fingerprint와 지금까지 검증한 종목 수, 누적 거래 수를 알려주세요.")
        after = self._research_tool_call_count()
        self.assertEqual(before, after, "zero new research tool calls for a read-only identity/progress question")
        mission = self._mission()
        candidate_turn3 = candidate_records(mission)[0]
        self.assertEqual(candidate_turn3.candidate_id, candidate.candidate_id)
        self.assertEqual(candidate_turn3.strategy_fingerprint, candidate.strategy_fingerprint)
        self.assertIn(candidate.strategy_fingerprint[:16], turn3)
        self.assertIn(str(candidate_turn3.valid_symbols), turn3)
        self.assertIn(str(candidate_turn3.trade_count), turn3)
        self.assertGreaterEqual(candidate_turn3.valid_symbols, baseline_valid_symbols)
        self.assertGreaterEqual(candidate_turn3.trade_count, baseline_trade_count)

        # ------------------------------------------------------------
        # Turn 4: "현재 후보를 그대로 유지한 채 강건성 검증을 계속해주세요."
        # - the actual mission-driven research cycle must still execute.
        # ------------------------------------------------------------
        before = self._research_tool_call_count()
        self._send(7, "현재 후보를 그대로 유지한 채 강건성 검증을 계속해주세요.", force_hold=True)
        after = self._research_tool_call_count()
        self.assertGreater(after, before, "an explicit continuation request must still execute a bounded research cycle")
        mission = self._mission()
        candidate_turn4 = candidate_records(mission)[0]
        self.assertEqual(candidate_turn4.candidate_id, candidate.candidate_id, "continuation must never rotate the candidate")
        self.assertEqual(candidate_turn4.strategy_fingerprint, candidate.strategy_fingerprint)
        self.assertGreaterEqual(candidate_turn4.valid_symbols, baseline_valid_symbols)
        self.assertGreaterEqual(candidate_turn4.trade_count, baseline_trade_count)

        # ------------------------------------------------------------
        # Turn 5: "현재 단타 전략은 몇 점 정도인가요? 점수를 산정할 근거가
        # 부족하면 부족하다고 말하고, 현재 확보된 실제 검증 수치를 함께
        # 보여주세요."
        # ------------------------------------------------------------
        before = self._research_tool_call_count()
        turn5 = self._send(
            8,
            "현재 단타 전략은 몇 점 정도인가요? 점수를 산정할 근거가 부족하면 부족하다고 말하고, "
            "현재 확보된 실제 검증 수치를 함께 보여주세요.",
        )
        after = self._research_tool_call_count()
        self.assertEqual(before, after, "a score question must never re-execute research")
        self.assertIn("score_status=insufficient_evidence", turn5)
        self.assertIsNone(_FABRICATED_SCORE_PATTERN.search(turn5), "no fabricated numeric score may appear")
        mission = self._mission()
        candidate_turn5 = candidate_records(mission)[0]
        self.assertIn(str(candidate_turn5.valid_symbols), turn5)
        self.assertIn(str(candidate_turn5.trade_count), turn5)

        # ------------------------------------------------------------
        # Turn 6: "현재 단타 전략을 설명해주세요." - must never regress to
        # a stale single-symbol 0-trade explanation (the reported
        # production 5 -> 25 -> 0 regression).
        # ------------------------------------------------------------
        before = self._research_tool_call_count()
        turn6 = self._send(9, "현재 단타 전략을 설명해주세요.")
        after = self._research_tool_call_count()
        self.assertEqual(before, after, "a strategy-explanation question must never execute a research tool")
        mission = self._mission()
        candidate_turn6 = candidate_records(mission)[0]
        self.assertIn(candidate_turn6.candidate_id, turn6)
        self.assertIn(candidate_turn6.strategy_fingerprint[:16], turn6)
        self.assertGreaterEqual(candidate_turn6.valid_symbols, baseline_valid_symbols)
        self.assertGreaterEqual(candidate_turn6.trade_count, baseline_trade_count)
        self.assertNotIn("거래 표본: 0회", turn6)
        self.assertNotIn("계산 불가", turn6)
        for token in _LEGACY_V5_TOKENS:
            self.assertNotIn(token, turn6)


if __name__ == "__main__":
    unittest.main()
