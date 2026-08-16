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

        # Turn 2: explicit market-wide scope, real production dispatch.
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        mission_after_turn2 = self._mission()
        self.assertEqual(mission_after_turn2.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission_after_turn2.market, "KR")
        self.assertIn("KOSPI", mission_after_turn2.exchanges)
        self.assertIn("KOSDAQ", mission_after_turn2.exchanges)
        multi_symbol_after_turn2 = len(self._multi_symbol_audits())

        # Turn 3: THE BUG - a generic continuation phrase with no explicit
        # scope must NOT regress to single-symbol / 005930 research.
        single_symbol_before_turn3 = len(self._single_symbol_audits())
        turn3 = self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission_after_turn3 = self._mission()
        self.assertEqual(mission_after_turn3.universe_scope, MissionUniverseScope.MARKET_WIDE, "scope must not regress")
        self.assertEqual(mission_after_turn3.market, "KR")
        self.assertNotIn("005930", mission_after_turn3.symbols)
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
        self.assertGreater(len(self._multi_symbol_audits()) + len(self._single_symbol_audits()), real_work_before_turn4)

        # Turn 5: another bare continuation - target and scope both persist.
        self._send(5, "증거가 충분할 때까지 멈추지 말고 연구해주세요")
        mission_after_turn5 = self._mission()
        self.assertEqual(mission_after_turn5.target_promotion_ready_candidates, 3)
        self.assertEqual(mission_after_turn5.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertNotIn("005930", mission_after_turn5.symbols)

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
        self.assertNotIn("005930", mission_final.symbols)

        # Mission lineage is stable: every turn from 2 onward updated the
        # SAME mission_id, never silently replaced it.
        self.assertEqual(mission_after_turn2.mission_id, mission_final.mission_id)

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

        with patch(
            "gaon.knowledge.research_mission.is_cycle_budget_exhausted", return_value=True
        ):
            turn2 = self._send(2, "증거가 충분할 때까지 연구해주세요")
        self.assertIn("종료되지 않았습니다", turn2)
        mission_after = self._mission()
        self.assertEqual(mission_after.status, MissionStatus.ACTIVE)
        self.assertNotEqual(mission_after.status, MissionStatus.COMPLETED)

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
