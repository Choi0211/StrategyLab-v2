"""Patch 8.1 - persistent autonomous Research Mission acceptance test.

Replays (closely) the real Telegram conversation that exposed the scope-
regression defect: after a user establishes a market-wide KR research
scope, generic continuation messages such as "증거가 충분할 때까지
연구해주세요" must keep researching within that scope instead of silently
collapsing back to a single symbol (005930, Samsung Electronics) - see
``gaon.knowledge.research_mission`` for the mission model and
``LLMConversationBrain._try_mission_driven_research_cycle`` for the guard.

Runs through the REAL production stack (TelegramConversationAgent ->
LLMConversationBrain -> default_tool_registry -> multi_symbol_research /
telegram_autonomous_learning_payload), mocking only the true external
boundaries:

- ``gaon.research.krx_real_pipeline.krx_real_research_payload`` (single-
  symbol real-data fetch, used by turn 1's fresh single-symbol research and
  by any Autonomous Learning V2 fallback).
- ``gaon.knowledge.telegram_autonomous_learning._run_production_external_research``
  (external/academic evidence acquisition).
- ``gaon.research.multi_symbol.build_market_data_provider_from_env`` (the
  market-data provider multi-symbol research uses for both universe
  selection and per-symbol bars) - replaced with a deterministic, network-
  free fixture-backed KR universe so market-wide research is exercised for
  real instead of skipped.
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import MissionStatus, MissionUniverseScope
from gaon.research.krx_real_pipeline import KRXFixtureMarketDataProvider
from gaon.research.real_research import MarketSymbol
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent


def _config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
        assistant_enabled=False,
    )


def _update(update_id: int, message_id: int, text: str, *, chat_id: int = 100) -> dict:
    return {"update_id": update_id, "message": {"message_id": message_id, "chat": {"id": chat_id}, "from": {"id": 200}, "text": text}}


class _RecordingTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _baseline(*, trades: int, run_id: str) -> dict[str, object]:
    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": f"fp:candidate:{run_id}", "rules": ["breakout", "volume"]}
    return {
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart",
                "fixture_backed": False,
                "rows": 1222,
                "start_date": "2021-07-25",
                "end_date": "2026-07-24",
            }
        },
        "quality": {"status": "pass", "blocking_findings": []},
        "strategy": strategy,
        "validation": {"symbols": 5, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
        "backtest": {"source": "real", "metrics": {"trade_count": trades, "total_return": 0.12, "mdd": 0.08}},
        "candidates": [
            {
                "candidate_id": "candidate:005930:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": f"backtest:candidate:{run_id}",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": trades, "total_return": 0.13, "mdd": 0.07, "profit_factor": 1.4},
                },
            }
        ],
    }


_MISSION_TEST_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("005930", "KOSPI"),
    ("000660", "KOSPI"),
    ("005380", "KOSPI"),
    ("051910", "KOSPI"),
    ("105560", "KOSPI"),
    ("035420", "KOSDAQ"),
    ("068270", "KOSDAQ"),
    ("035720", "KOSDAQ"),
    ("086520", "KOSDAQ"),
    ("091990", "KOSDAQ"),
)


class _DeterministicKRUniverseProvider:
    """A fixture-backed, network-free stand-in for the real KIS-master +
    Yahoo provider that market-wide multi-symbol research uses in
    production. Reuses the existing ``KRXFixtureMarketDataProvider`` for
    per-symbol bars/quality (the same deterministic generator every other
    unit test in this repo already trusts) and only adds the
    ``fetch_universe`` capability real market-wide research needs, so this
    test exercises the real curated-universe-selection code path instead
    of skipping it."""

    source = "fixture:mission-test-universe"
    market_agnostic = True

    def __init__(self) -> None:
        self._fixture = KRXFixtureMarketDataProvider()

    @classmethod
    def from_env(cls, env=None):
        return cls()

    def fetch_universe(self, market):
        return tuple(MarketSymbol(code, code, "KR", exchange) for code, exchange in _MISSION_TEST_UNIVERSE)

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily"):
        return self._fixture.fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)

    def validate_dataset(self, dataset):
        return self._fixture.validate_dataset(dataset)


# Routes the OLD single-symbol continuation path used before Patch 8.1's
# scope-regression guard - a mission-driven turn must never record one of
# these, since they sit behind _resolve_autonomous_symbol's 005930 fallback.
_OLD_SINGLE_SYMBOL_CONTINUATION_ROUTES = frozenset(
    {
        "conversation_autonomous_learning_v2",
        "conversation_autonomous_research_cycle",
        "conversation_autonomous_continuation",
        "conversation_autonomous_critique",
    }
)


class PersistentResearchMissionConversationTests(unittest.TestCase):
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

    def _multi_symbol_audits(self):
        return self.store.tool_audit.list(tool_name="multi_symbol_research")

    def _single_symbol_audits(self):
        return self.store.tool_audit.list(tool_name="autonomous_learning_research") + self.store.tool_audit.list(
            tool_name="autonomous_research_cycle"
        )

    def _latest_route(self) -> str:
        # ULTRAREVIEW false-positive repair: the ground truth for "which
        # code path actually handled this turn" is the route recorded on
        # the stored assistant message, not an inference from mission
        # fields that can be trivially empty either way (e.g. `symbols`
        # is always () for a market_wide mission whether or not the
        # regression is present). The user's own message is also stored,
        # with route="input" and the same created_at timestamp as the
        # assistant's reply, so this must filter by role rather than
        # assume ordering - a tied created_at can sort either message
        # first.
        messages = self.store.conversations.list_messages("telegram:100", limit=5)
        assistant_messages = [message for message in messages if message.role == "assistant"]
        self.assertTrue(assistant_messages, "no assistant conversation message recorded")
        return assistant_messages[-1].route

    def test_real_conversation_preserves_market_wide_scope_across_generic_continuations(self) -> None:
        # Turn 1: original goal statement. Objective + strategy family are
        # captured; the exact starting scope (which the original defect
        # report does not consider a bug) is not asserted here.
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요.\n"
            "현재 등록되어있는 전략보다 수익면에서나 안전성 면에서 뛰어나야합니다.",
        )
        mission_after_turn1 = self._mission()
        self.assertIsNotNone(mission_after_turn1)
        self.assertTrue(mission_after_turn1.improve_return)
        self.assertTrue(mission_after_turn1.improve_safety)
        self.assertEqual(mission_after_turn1.strategy_family, "short_term_daytrade")

        # Turn 2: explicit market-wide scope declaration. With
        # assistant_enabled=False (this harness's deterministic-testing
        # convention, matching test_gaon_end_to_end_conversation.py), a
        # FRESH explicit multi-symbol request is only dispatched to a real
        # tool by the LLM-provider path (_try_authoritative_research_tool),
        # which is unreachable here - so this turn makes zero tool calls.
        # What IS proven here, and is the thing this turn exists to prove,
        # is that the mission's scope fields are established from the text
        # alone (extract_or_update_mission), independent of whether a tool
        # actually ran - turns 3/5/6 below are what prove real dispatch.
        multi_symbol_before_turn2 = len(self._multi_symbol_audits())
        single_symbol_before_turn2 = len(self._single_symbol_audits())
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self.assertEqual(len(self._multi_symbol_audits()), multi_symbol_before_turn2)
        self.assertEqual(len(self._single_symbol_audits()), single_symbol_before_turn2)
        mission_after_turn2 = self._mission()
        self.assertEqual(mission_after_turn2.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission_after_turn2.market, "KR")
        self.assertIn("KOSPI", mission_after_turn2.exchanges)
        self.assertIn("KOSDAQ", mission_after_turn2.exchanges)
        multi_symbol_after_turn2 = len(self._multi_symbol_audits())

        # Turn 3: THE BUG - a generic continuation phrase with no explicit
        # scope must NOT regress to single-symbol / 005930 research. The
        # ground-truth check is the actual route the conversation brain
        # recorded for this turn (see _latest_route): it must be one of the
        # NEW mission-driven routes, and specifically must NOT be the OLD
        # single-symbol continuation route
        # (conversation_autonomous_learning_v2 / _autonomous_research_cycle)
        # that _resolve_autonomous_symbol's 005930 fallback lives behind -
        # checking `"005930" not in mission.symbols` alone would be vacuous,
        # since a market_wide mission's `symbols` tuple is always empty by
        # construction whether or not the regression is present.
        single_symbol_before_turn3 = len(self._single_symbol_audits())
        turn3 = self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission_after_turn3 = self._mission()
        self.assertEqual(mission_after_turn3.universe_scope, MissionUniverseScope.MARKET_WIDE, "scope must not regress")
        self.assertEqual(mission_after_turn3.market, "KR")
        route_turn3 = self._latest_route()
        self.assertTrue(route_turn3.startswith("conversation_mission_"), f"unexpected route for turn 3: {route_turn3}")
        self.assertNotIn(route_turn3, _OLD_SINGLE_SYMBOL_CONTINUATION_ROUTES)
        self.assertGreater(len(self._multi_symbol_audits()), multi_symbol_after_turn2, "continuation must dispatch a real multi-symbol cycle")
        self.assertEqual(len(self._single_symbol_audits()), single_symbol_before_turn3, "continuation must not silently fall back to single-symbol research")
        self.assertTrue(turn3.strip())
        self.assertNotIn("안전 검증을 통과하지 못했습니다", turn3)

        # Turn 4: target candidate count established; scope must still hold.
        # A mission-driven continuation alternates between a coverage cycle
        # (multi_symbol_research) and, once coverage flags a strongest
        # symbol, one bounded per-candidate Research Director cycle
        # (autonomous_learning_research) - either is real mission-driven
        # work, so this asserts on their combined total rather than
        # over-specifying which one fires on any given turn.
        real_work_before_turn4 = len(self._multi_symbol_audits()) + len(self._single_symbol_audits())
        self._send(4, "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올 때까지 연구해주세요")
        mission_after_turn4 = self._mission()
        self.assertEqual(mission_after_turn4.target_promotion_ready_candidates, 3)
        self.assertEqual(mission_after_turn4.universe_scope, MissionUniverseScope.MARKET_WIDE)
        route_turn4 = self._latest_route()
        self.assertTrue(route_turn4.startswith("conversation_mission_"), f"unexpected route for turn 4: {route_turn4}")
        self.assertNotIn(route_turn4, _OLD_SINGLE_SYMBOL_CONTINUATION_ROUTES)
        self.assertGreater(len(self._multi_symbol_audits()) + len(self._single_symbol_audits()), real_work_before_turn4)

        # Turn 5: another bare continuation - target and scope both persist.
        self._send(5, "증거가 충분할 때까지 멈추지 말고 연구해주세요")
        mission_after_turn5 = self._mission()
        self.assertEqual(mission_after_turn5.target_promotion_ready_candidates, 3)
        self.assertEqual(mission_after_turn5.universe_scope, MissionUniverseScope.MARKET_WIDE)
        route_turn5 = self._latest_route()
        self.assertTrue(route_turn5.startswith("conversation_mission_"), f"unexpected route for turn 5: {route_turn5}")
        self.assertNotIn(route_turn5, _OLD_SINGLE_SYMBOL_CONTINUATION_ROUTES)

        # Turn 6: the exact phrase that produced the opaque safety-gate
        # message in production. It must now produce a real, mission-aware
        # response and must never regress scope.
        turn6 = self._send(6, "승격 가능한 게 나올 때까지 연구해달라구요")
        self.assertTrue(turn6.strip())
        self.assertNotIn("안전 검증을 통과하지 못했습니다", turn6)
        mission_final = self._mission()
        self.assertEqual(mission_final.target_promotion_ready_candidates, 3)
        self.assertEqual(mission_final.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission_final.market, "KR")
        self.assertIn("KOSPI", mission_final.exchanges)
        self.assertIn("KOSDAQ", mission_final.exchanges)
        route_turn6 = self._latest_route()
        self.assertTrue(route_turn6.startswith("conversation_mission_"), f"unexpected route for turn 6: {route_turn6}")
        self.assertNotIn(route_turn6, _OLD_SINGLE_SYMBOL_CONTINUATION_ROUTES)

        # Mission lineage is stable: every turn from 2 onward updated the
        # SAME mission_id, never silently replaced it.
        self.assertEqual(mission_after_turn2.mission_id, mission_final.mission_id)

        # H2 regression: whenever the SAME candidate symbol is validated
        # across consecutive promotion cycles (turns 4-6 keep re-entering
        # _try_mission_promotion_cycle for the same pending_promotion_symbol
        # as long as the Director has not reached a terminal decision),
        # steps_used must carry forward instead of resetting to 0 every
        # turn - otherwise the Research Director can never advance through
        # its validation stages and the mission can never converge.
        steps_used_sequence = [
            int(audit.request["arguments"].get("steps_used", 0)) for audit in self._single_symbol_audits()
        ]
        if len(steps_used_sequence) >= 2:
            self.assertEqual(
                steps_used_sequence,
                sorted(steps_used_sequence),
                f"steps_used must be non-decreasing across mission promotion cycles, got {steps_used_sequence}",
            )
            self.assertGreater(
                steps_used_sequence[-1], 0, "steps_used must have advanced past 0 on a later promotion cycle"
            )

        # Bounded execution: each mission-driven turn made a small, bounded
        # number of tool calls (never more than a couple), not an unbounded
        # loop within one request.
        for audit in self._multi_symbol_audits():
            self.assertFalse(audit.result["output"].get("automatic_order", False))
            self.assertFalse(audit.result["output"].get("automatic_champion_promotion", False))
            self.assertFalse(audit.result["output"].get("automatic_config_apply", False))

    def test_budget_exhaustion_within_one_cycle_does_not_complete_the_mission(self) -> None:
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

        # ULTRAREVIEW false-positive repair: llm_conversation.py does
        # `from gaon.knowledge.research_mission import ... is_cycle_budget_exhausted`,
        # which binds the name into llm_conversation's OWN module namespace
        # at import time - patching the source module's attribute (as the
        # original version of this test did) does not affect that already-
        # bound reference and is silently inert. The correct patch target
        # is where the name is actually looked up from at call time.
        with patch(
            "gaon.runtime.llm_conversation.is_cycle_budget_exhausted", return_value=True
        ) as mocked:
            turn2 = self._send(2, "증거가 충분할 때까지 연구해주세요")
        self.assertTrue(mocked.called, "the patched budget-exhaustion signal was never consulted - this mock is not load-bearing")
        self.assertIn("종료되지 않았습니다", turn2)
        mission_after = self._mission()
        self.assertEqual(mission_after.status, MissionStatus.ACTIVE)
        self.assertNotEqual(mission_after.status, MissionStatus.COMPLETED)

    def test_explain_follow_up_with_active_mission_makes_no_research_tool_call(self) -> None:
        # H3 regression: "이어서 설명해주세요" (please continue *explaining*)
        # must never be hijacked into a research cycle just because it
        # shares a word with a real continuation phrase.
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "증거가 충분할 때까지 연구해주세요")
        multi_symbol_before = len(self._multi_symbol_audits())
        single_symbol_before = len(self._single_symbol_audits())
        self._send(3, "이어서 설명해주세요")
        self.assertEqual(len(self._multi_symbol_audits()), multi_symbol_before)
        self.assertEqual(len(self._single_symbol_audits()), single_symbol_before)

    def test_generic_continuation_with_active_mission_makes_a_research_tool_call(self) -> None:
        # H3 regression, positive case: a genuine continuation phrase must
        # still dispatch real mission-driven work.
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        real_work_before = len(self._multi_symbol_audits()) + len(self._single_symbol_audits())
        self._send(2, "계속 연구해주세요")
        self.assertGreater(len(self._multi_symbol_audits()) + len(self._single_symbol_audits()), real_work_before)

    def test_no_order_promotion_or_mutation_across_the_whole_conversation(self) -> None:
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        self._send(3, "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올 때까지 연구해주세요")
        self._send(4, "증거가 충분할 때까지 멈추지 말고 연구해주세요")
        for audit in self._multi_symbol_audits():
            output = audit.result["output"]
            self.assertFalse(output.get("automatic_order", False))
            self.assertFalse(output.get("automatic_champion_promotion", False))
            self.assertFalse(output.get("automatic_config_apply", False))
        for audit in self._single_symbol_audits():
            output = audit.result["output"]
            self.assertFalse(output.get("strategy_mutated", False))
            self.assertFalse(output.get("order_executed", False))
            self.assertFalse(output.get("automatic_champion_promotion", False))
            self.assertFalse(output.get("broker_order_called", False))
            self.assertFalse(output.get("kis_order_called", False))


if __name__ == "__main__":
    unittest.main()
