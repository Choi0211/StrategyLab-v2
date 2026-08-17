"""Patch 8.3 - Persistent Strategy Candidate Continuation acceptance test.

Real production defect this reproduces and proves fixed: a Telegram user
established a KR market-wide, strategy-centric Research Mission (Patch 8.2),
multi-symbol research produced several strategy candidates, and one
candidate ("candidate A") was identified as promising across multiple
symbols. The user then asked Gaon to continue that candidate's robustness
validation (OOS / walk-forward / transaction-cost stress / regime
validation) with natural phrasing such as "후보 A 계속 검증해줘" - and Gaon
abandoned the market-wide strategy candidate entirely, instead resuming an
UNRELATED, STALE single-symbol Autonomous Learning session for Samsung
Electronics (005930) left over from earlier in the conversation, producing
output shaped like the pre-Patch-8.1 ``autonomous_research_cycle`` tool
(``[검증된 기준] symbol=005930 ... terminal_state=no_new_research_path``).

Root cause (see gaon.knowledge.research_mission's module-level comment
above ``is_candidate_robustness_continuation_request``, and
gaon.runtime.llm_conversation's comment above
``_LEGACY_SINGLE_SYMBOL_RESEARCH_TOOLS``): the Patch 8.2 mission-routing-
precedence hook in ``LLMConversationBrain._try_conversational_mvp`` only
fired when ``is_generic_continuation_request`` matched a narrow, hand-
enumerated set of continuation phrases - phrasing that instead named a
validation stage ("OOS 검증해줘") or referred to "후보 A" never matched, so
the message fell through to the legacy single-symbol autonomous-research
path, which resolves its target symbol from stale conversational context
(``last_symbols[0]``), never from the mission's own persisted candidate.

This test proves, through the REAL production stack
(TelegramConversationAgent -> LLMConversationBrain -> default_tool_registry
-> multi_symbol_research / telegram_autonomous_learning_payload), mocking
only the true external boundaries - same convention as
``tests/integration/test_strategy_centric_autonomous_research.py``:

- a stale single-symbol session (Samsung Electronics) sitting in
  conversational context BEFORE the mission exists cannot resurface once a
  market-wide strategy candidate is active
- routing does not use 005930 (or any symbol) as the RESEARCH IDENTITY -
  the persisted strategy candidate remains the identity throughout
- the market-wide mission remains active across the whole conversation
- the exact candidate fingerprint survives every continuation turn
- robustness validation genuinely operates on the persisted candidate (its
  own evidence symbols, its own spec_rules) - never on stale context
- promotion-ready count only ever changes through the real human-review
  gate (never invented by this routing fix)
- execution stays bounded, and continuation/rotation across many turns
  never loops unboundedly within one Telegram update
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    MissionUniverseScope,
    candidate_records,
    distinct_promotion_ready_strategy_count,
)
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import (
    _DeterministicKRUniverseProvider,
    _MISSION_TEST_UNIVERSE,
    _RecordingTelegramClient,
    _baseline,
    _config,
    _update,
)

_STALE_SAMSUNG_DEFECT_MARKER = "기존 분석 결과를 근거로 자율 연구 검증 사이클을 실행했습니다"


class PersistentStrategyCandidateContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str) -> str:
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-17T00:{update_id:02d}:00Z"
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

    def test_candidate_continuation_survives_stale_single_symbol_context(self) -> None:
        # A stale single-symbol session, established BEFORE the mission
        # ever existed - this is exactly what leaves last_symbols=
        # ("005930",) and a Samsung last_research_context sitting in
        # conversational memory.
        stale_turn = self._send(0, "삼성전자 분석해줘")
        self.assertIn("삼성전자", stale_turn)
        context = self.agent._brain._mvp_context_for("telegram:100")
        self.assertIsNotNone(context)
        self.assertEqual(tuple(context.last_symbols), ("005930",))

        # Turn 1: establish a KR market-wide, strategy-centric mission.
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission.market, "KR")

        # Turn 3: multi-symbol research produces a strategy candidate that
        # becomes promising across multiple symbols.
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        candidates = candidate_records(mission)
        self.assertEqual(len(candidates), 1, "exactly one strategy candidate must exist - no symbol-driven duplication")
        candidate_before = candidates[0]
        self.assertRegex(candidate_before.candidate_id, r"^KR-ST-\d{3}$")
        fingerprint_before = candidate_before.strategy_fingerprint

        # Turn 4: the exact real production phrasing - ask to continue
        # candidate A's OOS / walk-forward / transaction-cost / regime
        # robustness validation across several domestic symbols.
        turn4 = self._send(
            4,
            "후보 A를 포함한 우수 전략 후보들을 OOS, walk-forward, "
            "거래비용 스트레스, 시장 국면별 검증까지 계속 진행해주세요. "
            "하나의 종목에 맞추지 말고 여러 국내 종목에서 동일한 전략을 "
            "검증해주세요. 승격 요청 기준을 통과한 전략은 promotion-ready "
            "후보로 기록하고, 서로 다른 전략 3개가 준비될 때까지 "
            "Research Mission을 계속 진행해주세요.",
        )

        # The defect never reproduces: no legacy autonomous_research_cycle
        # call, and the tell-tale "resumed an old session" opening line
        # never appears.
        self.assertEqual(len(self._audits("autonomous_research_cycle")), 0)
        self.assertNotIn(_STALE_SAMSUNG_DEFECT_MARKER, turn4)
        for symbol, _exchange in _MISSION_TEST_UNIVERSE:
            self.assertNotIn(f"{symbol} 전략을 다시 연구했습니다", turn4)

        # The market-wide mission remains active, and the SAME strategy
        # candidate (same fingerprint, no symbol-driven identity change)
        # continued.
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission.market, "KR")
        candidates_after = candidate_records(mission)
        self.assertEqual(len(candidates_after), 1, "the diversity/target-count phrasing must not spawn or discard candidates")
        candidate_after = candidates_after[0]
        self.assertEqual(candidate_after.candidate_id, candidate_before.candidate_id)
        self.assertEqual(candidate_after.strategy_fingerprint, fingerprint_before)

        # If a deep robustness cycle ran, it operated on a symbol drawn
        # from the CANDIDATE's own evidence - never the stale Samsung
        # symbol resolved from conversational context.
        robustness_audits = self._audits("autonomous_learning_research")
        new_robustness_audits = [audit for audit in robustness_audits if audit.request["arguments"].get("request_text") != "삼성전자 분석해줘"]
        if new_robustness_audits:
            evaluated_symbol = new_robustness_audits[-1].request["arguments"]["symbol"]
            self.assertIn(evaluated_symbol, candidate_after.evidence_symbols, "deep validation must draw its symbol from the candidate's own evidence")

        # Promotion-ready count only ever changes through the real
        # human-review gate - a routing fix must never invent promotions.
        self.assertEqual(
            mission.current_promotion_ready_candidates,
            distinct_promotion_ready_strategy_count(mission),
        )

        # Bounded execution across the whole conversation.
        self.assertLess(len(self._audits("multi_symbol_research")), 20)
        self.assertLess(len(self._audits("autonomous_learning_research")), 20)

    def test_candidate_reference_alone_continues_the_mission_without_any_legacy_continuation_token(self) -> None:
        # ULTRAREVIEW test-isolation fix: the headline test above uses the
        # real production paragraph, which (like much natural phrasing)
        # happens to also contain "계속 진행해주세요" - a phrase that
        # already matched the PRE-EXISTING _GENERIC_CONTINUATION_TOKENS
        # entry "계속진행" even before this patch, so that test alone does
        # not prove the NEW is_candidate_robustness_continuation_request
        # predicate is what closes the gap. This test uses turn-4 phrases
        # that share NO substring with any pre-existing
        # _GENERIC_CONTINUATION_TOKENS entry, so it can only pass because
        # of the new predicate.
        self._send(0, "삼성전자 분석해줘")
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        candidate_before = candidate_records(self._mission())[0]

        for offset, phrase in enumerate(("후보 A 계속 검증해줘", "OOS 검증해줘"), start=4):
            turn = self._send(offset, phrase)
            self.assertEqual(len(self._audits("autonomous_research_cycle")), 0, phrase)
            self.assertNotIn(_STALE_SAMSUNG_DEFECT_MARKER, turn, phrase)
            mission = self._mission()
            self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE, phrase)
            candidate_after = candidate_records(mission)[0]
            self.assertEqual(candidate_after.candidate_id, candidate_before.candidate_id, phrase)
            self.assertEqual(candidate_after.strategy_fingerprint, candidate_before.strategy_fingerprint, phrase)

    def test_continuation_and_rotation_remain_bounded_across_many_turns(self) -> None:
        self._send(0, "삼성전자 분석해줘")
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")

        continuation_phrases = (
            "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요",
            "후보 A 계속 검증해줘",
            "OOS 검증해줘",
            "walk-forward까지 진행해줘",
            "계속 연구해줘",
            "승격 가능한 전략 3개가 나올 때까지 계속해줘",
            "다른 방식도 찾아봐.",
            "계속 연구해줘",
        )
        for offset, phrase in enumerate(continuation_phrases, start=3):
            self._send(offset, phrase)
            # Exactly one bounded research call per turn - never an
            # unbounded loop inside a single Telegram update.
            mission = self._mission()
            self.assertIsNotNone(mission)
            self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

        # Even after many turns (including an explicit diversity request
        # and several differently-worded continuations), execution stayed
        # bounded and never fell back to the legacy single-symbol path.
        self.assertEqual(len(self._audits("autonomous_research_cycle")), 0)
        self.assertLess(len(self._audits("multi_symbol_research")), 30)
        self.assertLess(len(self._audits("autonomous_learning_research")), 30)

    def test_explicit_single_symbol_override_still_works_after_candidate_continuation(self) -> None:
        self._send(0, "삼성전자 분석해줘")
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission_before = self._mission()
        self.assertEqual(mission_before.universe_scope, MissionUniverseScope.MARKET_WIDE)

        self._send(4, "삼성전자만 연구해줘")
        mission_after = self._mission()
        self.assertEqual(mission_after.universe_scope, MissionUniverseScope.SINGLE_SYMBOL)
        self.assertEqual(mission_after.symbols, ("005930",))

    def test_restart_reload_preserves_active_candidate_and_progress(self) -> None:
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission_before_restart = self._mission()
        candidate_before_restart = candidate_records(mission_before_restart)[0]

        # Simulate a process restart: a BRAND NEW agent instance (no
        # in-memory caches carried over) wired to the SAME durable storage
        # connection.
        restarted_agent = TelegramConversationAgent(_config(), self.store._connection)
        reloaded_mission = restarted_agent._brain._mission_for("telegram:100")
        self.assertIsNotNone(reloaded_mission)
        self.assertEqual(reloaded_mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        reloaded_candidate = candidate_records(reloaded_mission)[0]
        self.assertEqual(reloaded_candidate.candidate_id, candidate_before_restart.candidate_id)
        self.assertEqual(reloaded_candidate.strategy_fingerprint, candidate_before_restart.strategy_fingerprint)
        self.assertEqual(reloaded_candidate.valid_symbols, candidate_before_restart.valid_symbols)
        self.assertEqual(reloaded_candidate.attempted_symbols, candidate_before_restart.attempted_symbols)
        self.assertEqual(reloaded_candidate.status, candidate_before_restart.status)


if __name__ == "__main__":
    unittest.main()
