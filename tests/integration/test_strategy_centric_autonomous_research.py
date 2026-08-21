"""Patch 8.2 - strategy-centric autonomous research acceptance test.

Replays the real production conversation that exposed the symbol-vs-
strategy identity defect: even after Patch 8.1 fixed the market-wide scope
regression, Gaon kept treating a SYMBOL (e.g. "473050") as a strategy's
identity - "영하님, 473050 전략을 다시 연구했습니다." on every continuation,
instead of evaluating ONE strategy candidate's rules across many symbols.

This test proves:
- the primary research object is a strategy candidate (KR-ST-NNN), not a
  symbol
- candidate fingerprints are symbol-independent (the SAME candidate
  evaluated on many symbols is ONE strategy, never many)
- multi-symbol research audits carry the active candidate's exact rules
  (``candidate_spec``), proving cross-symbol evaluation of one strategy
- promotion-ready count is the number of DISTINCT strategy fingerprints,
  never symbols
- generic continuation never falls back to a single-symbol identity
- execution stays bounded (a small number of tool calls per turn)
- no order/promotion/strategy-mutation/approval-bypass anywhere

Runs through the REAL production stack (TelegramConversationAgent ->
LLMConversationBrain -> default_tool_registry -> multi_symbol_research /
telegram_autonomous_learning_payload), mocking only the true external
boundaries - same convention as
``tests/integration/test_persistent_research_mission_conversation.py``.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    DEFAULT_KR_EXCHANGES,
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    add_candidate,
    candidate_records,
    distinct_promotion_ready_strategy_count,
    set_active_candidate,
)
from gaon.knowledge.strategy_candidate import (
    STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_TEMPLATES,
    build_candidate_spec,
    candidate_sample_exhausted,
    mark_stagnant,
    new_candidate,
    record_breadth_progress,
    record_robustness_progress,
    spec_rules_to_json,
)
from gaon.research.krx_real_pipeline import KRXFixtureMarketDataProvider
from gaon.research.real_research import MarketSymbol
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation import ConversationInput
from gaon.runtime.llm_conversation import LLMConversationRequest
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
    ("473050", "KOSDAQ"),
    ("068270", "KOSDAQ"),
    ("035720", "KOSDAQ"),
    ("086520", "KOSDAQ"),
    ("091990", "KOSDAQ"),
)


class _DeterministicKRUniverseProvider:
    """Fixture-backed, network-free stand-in for the real KIS-master +
    Yahoo provider real market-wide research uses - see the identical
    fixture in test_persistent_research_mission_conversation.py."""

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


class StrategyCentricAutonomousResearchTests(unittest.TestCase):
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

    def test_real_conversation_evaluates_strategy_candidates_not_symbols(self) -> None:
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요.\n"
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission.market, "KR")

        turn3 = self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()

        # The primary research object is a strategy candidate, not a symbol.
        candidates = candidate_records(mission)
        self.assertGreaterEqual(len(candidates), 1, "a strategy candidate must have been generated")
        active = candidates[-1]
        self.assertRegex(active.candidate_id, r"^KR-ST-\d{3}$")
        self.assertTrue(active.strategy_family)
        self.assertIn(active.candidate_id, turn3)
        self.assertNotIn("473050 전략", turn3)
        self.assertNotIn("005930 전략", turn3)

        # Candidate fingerprints are symbol-independent - the fingerprint
        # actually stored on the mission must equal the fingerprint of the
        # SAME family template built for a totally different symbol.
        independent_spec = build_candidate_spec(active.strategy_family, placeholder_symbol="999999", created_at="2026-08-17T00:00:00Z")
        self.assertEqual(active.strategy_fingerprint, independent_spec.strategy_family_fingerprint)

        # The multi_symbol_research audit shows cross-symbol evaluation of
        # ONE candidate's rules (candidate_spec argument), not per-symbol
        # research.
        multi_symbol_audits = self._multi_symbol_audits()
        self.assertGreaterEqual(len(multi_symbol_audits), 1)
        cross_symbol_audit = multi_symbol_audits[-1]
        self.assertEqual(cross_symbol_audit.request["arguments"].get("candidate_spec"), dict(active.spec_rules))
        # It really did evaluate MULTIPLE symbols under that one spec.
        evidence = cross_symbol_audit.result["output"].get("evidence", [])
        symbols_seen = {item.get("symbol") for item in evidence if isinstance(item, dict)}
        self.assertGreater(len(symbols_seen), 1, "one candidate must be evaluated across more than one symbol")

        # Individual symbols appear as evidence, never as identity.
        self.assertTrue(active.evidence_symbols or active.excluded_symbols)

        turn4 = self._send(4, "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올 때까지 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.target_promotion_ready_candidates, 3)
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

        self._send(5, "증거가 충분할 때까지 멈추지 말고 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.target_promotion_ready_candidates, 3)
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)

        turn6 = self._send(6, "승격 가능한 게 나올 때까지 연구해달라구요")
        self.assertTrue(turn6.strip())
        self.assertNotIn("안전 검증을 통과하지 못했습니다", turn6)
        mission_final = self._mission()
        self.assertEqual(mission_final.target_promotion_ready_candidates, 3)
        self.assertEqual(mission_final.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(mission_final.market, "KR")

        # Promotion-ready count is the number of DISTINCT strategy
        # fingerprints, never a symbol count.
        self.assertEqual(
            mission_final.current_promotion_ready_candidates,
            distinct_promotion_ready_strategy_count(mission_final),
        )

        # Bounded execution: no single turn triggered an unbounded number
        # of tool calls.
        for audit_list in (self._multi_symbol_audits(), self._single_symbol_audits()):
            self.assertLess(len(audit_list), 20, "execution must stay bounded across 6 turns")

        # No order/promotion/mutation anywhere.
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

    def test_multiple_symbols_never_count_as_multiple_promotion_ready_candidates(self) -> None:
        # Requirement 4: running one candidate across many symbols must
        # never inflate the promotion-ready count.
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "계속 연구해주세요")
        self._send(3, "계속 연구해주세요")
        mission = self._mission()
        candidates = candidate_records(mission)
        self.assertLessEqual(len(candidates), 1, "repeated breadth cycles on one family must not spawn extra candidates")
        self.assertEqual(mission.current_promotion_ready_candidates, 0)

    def test_generic_continuation_never_falls_back_to_a_single_symbol_identity(self) -> None:
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "증거가 충분할 때까지 멈추지 말고 연구해주세요")
        turn3 = self._send(3, "승격 가능한 게 나올 때까지 연구해달라구요")
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        for symbol, _exchange in _MISSION_TEST_UNIVERSE:
            self.assertNotIn(f"{symbol} 전략을 다시 연구했습니다", turn3)

    def test_ticker_as_strategy_regression_never_reproduces_for_common_continuation_phrases(self) -> None:
        # ULTRAREVIEW High #2: the defect specifically reproduced for
        # "계속 연구해주세요" - a more common phrasing than the one
        # test_generic_continuation_never_falls_back_to_a_single_symbol_
        # identity above happens to use - because it can route through the
        # deep single-symbol robustness cycle's "still in progress" branch,
        # which used to splice the autonomous_learning_research tool's raw
        # "{symbol} 전략을 다시 연구했습니다" leading sentence into the
        # response verbatim. Every phrase the user actually sent in
        # production is exercised here, across enough turns to reach both
        # the breadth and the deep-validation cycle.
        texts = [self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")]
        for update_id, phrase in enumerate(
            (
                "계속 연구해주세요",
                "증거가 충분할 때까지 멈추지 말고 연구해주세요",
                "승격 가능한 게 나올 때까지 연구해주세요",
                "계속 연구해주세요",
                "계속 연구해주세요",
                "계속 연구해주세요",
            ),
            start=2,
        ):
            texts.append(self._send(update_id, phrase))
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        for text in texts:
            for symbol, _exchange in _MISSION_TEST_UNIVERSE:
                self.assertNotIn(f"{symbol} 전략을 다시 연구했습니다", text)

    def test_diversity_request_rotates_the_active_candidate(self) -> None:
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "증거가 충분할 때까지 연구해주세요")
        mission_before = self._mission()
        active_before = mission_before.active_candidate_id
        self.assertIsNotNone(active_before)

        self._send(3, "다른 방식도 찾아봐.")
        mission_after = self._mission()
        # The mission is retained (never abandoned), but the previously
        # active candidate is no longer active - a NEW strategy family is
        # being pursued.
        self.assertEqual(mission_after.mission_id, mission_before.mission_id)
        self.assertNotEqual(mission_after.active_candidate_id, active_before)
        candidates = candidate_records(mission_after)
        families = {candidate.strategy_family for candidate in candidates}
        self.assertGreaterEqual(len(families), 2, "a diversity request must bias toward a different strategy family")


class StrategySpaceExpansionTelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _seed_exhausted_mission(self) -> None:
        now = "2026-08-21T00:00:00Z"
        mission = ResearchMission(
            mission_id="research-mission:test-strategy-space-expansion",
            market="KR",
            universe_scope=MissionUniverseScope.MARKET_WIDE,
            symbols=(),
            exchanges=DEFAULT_KR_EXCHANGES,
            strategy_family="short_term_daytrade",
            improve_return=True,
            improve_safety=True,
            baseline_comparison="registered_strategy",
            target_promotion_ready_candidates=3,
            current_promotion_ready_candidates=0,
            promotion_ready_candidates=(),
            explored_symbols=(),
            status=MissionStatus.ACTIVE,
            blocked_reason=None,
            cycles_completed=4,
            created_at=now,
            updated_at=now,
            originating_request="release-check",
        )
        for index, template in enumerate(STRATEGY_FAMILY_TEMPLATES, start=1):
            candidate = new_candidate(template.family, sequence=index, now=now)
            candidate = record_breadth_progress(
                candidate,
                attempted=5,
                valid=3,
                trade_count=12,
                evidence_symbols=("005930", "000660", "005380"),
                excluded_symbols=("035420", "051910"),
                provider_blocked=False,
                now=now,
            )
            candidate = record_robustness_progress(
                candidate,
                director_action="RUN_REGIME",
                terminal=False,
                validation_stage_status={"regime_validation": "partial", "walk_forward": "partial"},
                symbol="005930",
                reference=f"release-check:failed-evidence:{template.family}",
                now=now,
            )
            mission = add_candidate(mission, mark_stagnant(candidate, now=now), now=now)
        mission = set_active_candidate(mission, None, now=now)
        self.agent.handle(ConversationInput("telegram", "100", "100", "seed", "안녕하세요 가온", now))
        seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "seed", now, "telegram:100:seed")
        self.agent._brain._remember_mission(seed, mission)

    def test_exhausted_family_space_expands_to_distinct_candidate_and_real_research_path(self) -> None:
        self._seed_exhausted_mission()
        before = candidate_records(self.agent._brain._mission_for("telegram:100"))
        before_fingerprints = {candidate.strategy_fingerprint for candidate in before}
        received_at = "2026-08-21T00:10:00Z"
        with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=_baseline(trades=45, run_id="expansion")), patch(
            "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
            return_value={"state": "content_unavailable"},
        ), patch(
            "gaon.research.multi_symbol.build_market_data_provider_from_env",
            return_value=_DeterministicKRUniverseProvider(),
        ):
            result = process_update(
                parse_update_result(_update(10, 10, "연구를 계속해주세요"), received_at=received_at),
                self.runtime,
                self.client,
            )

        self.assertEqual(result.status, "sent", result)
        mission = self.agent._brain._mission_for("telegram:100")
        records = candidate_records(mission)
        self.assertEqual(len(records), len(before) + 1)
        expanded = records[-1]
        self.assertIn(expanded.strategy_family, {template.family for template in STRATEGY_SPACE_EXPANSION_TEMPLATES})
        self.assertNotIn(expanded.strategy_fingerprint, before_fingerprints)
        for old in before:
            preserved = next(candidate for candidate in records if candidate.candidate_id == old.candidate_id)
            self.assertEqual(preserved.to_json(), old.to_json())
        audits = self.store.tool_audit.list(tool_name="multi_symbol_research")
        self.assertGreaterEqual(len(audits), 1)
        self.assertEqual(audits[-1].request["arguments"].get("candidate_spec"), dict(expanded.spec_rules))
        self.assertTrue(expanded.evidence_symbols or expanded.excluded_symbols)
        response = self.client.sent[-1][1]
        self.assertIn(expanded.candidate_id, response)
        self.assertNotIn("strategy_family_space_exhausted", response)
        self.assertEqual(len(self.store.tool_audit.list(tool_name="autonomous_learning_research")), 0)
        self.assertEqual(len(self.store.tool_audit.list(tool_name="autonomous_research_cycle")), 0)


class SampleExhaustionCandidateDecisionTelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    @staticmethod
    def _details(symbols: tuple[str, ...], trades: tuple[int, ...]) -> dict[str, dict[str, object]]:
        return {
            symbol: {
                "symbol": symbol,
                "eligible": True,
                "metrics": {"trade_count": trades[index]},
                "evidence_id": f"integration:sample-exhaustion:{symbol}",
                "quality_status": "pass",
                "source": "real:yahoo-chart",
                "fixture_backed": False,
            }
            for index, symbol in enumerate(symbols)
        }

    def _seed_sample_exhausted_candidate(self) -> None:
        now = "2026-08-22T00:00:00Z"
        symbols = tuple(f"S{i:02d}" for i in range(32))
        batches = (
            (symbols[:13], tuple([5] * 12 + [10])),
            (symbols[13:17], (8, 8, 8, 7)),
            (symbols[17:22], (7, 7, 6, 6, 6)),
            (symbols[22:27], (8, 8, 8, 8, 8)),
            (symbols[27:32], (6, 6, 6, 5, 5)),
        )
        candidate = new_candidate("breakout_slow_multi_confirmed", sequence=5, now=now)
        for batch_index, (batch_symbols, batch_trades) in enumerate(batches, start=1):
            candidate = record_breadth_progress(
                candidate,
                attempted=13 if batch_index == 1 else 5,
                valid=len(batch_symbols),
                trade_count=sum(batch_trades),
                evidence_symbols=batch_symbols,
                excluded_symbols=("BLOCKED",) if batch_index == len(batches) else (),
                provider_blocked=False,
                now=now,
                evidence_details=self._details(batch_symbols, batch_trades),
                sample_exhaustion_reason="candidate_pool_exhausted" if batch_index == len(batches) else None,
                breadth_summary={
                    "total_symbols": 33,
                    "eligible_symbols": 32,
                    "aggregate_trade_count": 201,
                    "latest_batch_valid_symbols": len(batch_symbols),
                    "latest_batch_trade_count": sum(batch_trades),
                },
            )
        mission = ResearchMission(
            mission_id="research-mission:test-sample-exhaustion",
            market="KR",
            universe_scope=MissionUniverseScope.MARKET_WIDE,
            symbols=(),
            exchanges=DEFAULT_KR_EXCHANGES,
            strategy_family="short_term_daytrade",
            improve_return=True,
            improve_safety=True,
            baseline_comparison="registered_strategy",
            target_promotion_ready_candidates=3,
            current_promotion_ready_candidates=0,
            promotion_ready_candidates=(),
            explored_symbols=(),
            status=MissionStatus.ACTIVE,
            blocked_reason=None,
            cycles_completed=5,
            created_at=now,
            updated_at=now,
            originating_request="integration-test",
            candidates=(candidate.to_json(),),
            active_candidate_id=candidate.candidate_id,
        )
        self.agent.handle(ConversationInput("telegram", "100", "100", "seed", "안녕하세요 가온", now))
        seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "seed", now, "telegram:100:seed")
        self.agent._brain._remember_mission(seed, mission)

    def test_pool_exhaustion_persists_and_next_turn_does_not_repeat_expand_sample(self) -> None:
        self._seed_sample_exhausted_candidate()
        # Recreate the agent over the same SQLite connection to prove the
        # decision uses persisted mission/candidate state, not only process
        # memory.
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        before_multi = len(self.store.tool_audit.list(tool_name="multi_symbol_research"))

        def fake_learning(
            _connection,
            request_text,
            *,
            symbol="005930",
            mode="research",
            storage_root=None,
            steps_used=0,
            max_steps=8,
            planned_action=None,
            planned_action_reason=None,
        ):
            return {
                "schema_version": 2,
                "tool": "autonomous_learning_research",
                "mode": mode,
                "symbol": symbol,
                "request_text": request_text,
                "autonomous_learning_v2": {
                    "research_director_decision": {"action": "hold", "reason": "bounded continuation", "terminal": False},
                    "research_director_steps_used": 1,
                    "planned_action_execution": {
                        "planned_action": planned_action,
                        "planned_action_reason": planned_action_reason,
                        "dispatched": bool(planned_action),
                    },
                    "autonomous_quant_partner": {
                        "production_grade_validation": {"out_of_sample": {"status": "pass", "executed": True}}
                    },
                    "promotion_candidate_context": {"candidate_id": "candidate:test", "candidate_fingerprint": "fp:test"},
                },
                "strategy_mutated": False,
                "order_executed": False,
                "automatic_champion_promotion": False,
                "broker_order_called": False,
                "kis_order_called": False,
                "safety": "pass",
            }

        with patch("gaon.runtime.llm_tools.telegram_autonomous_learning_payload", side_effect=fake_learning):
            result = process_update(
                parse_update_result(_update(20, 20, "연구를 계속해주세요"), received_at="2026-08-22T00:10:00Z"),
                self.runtime,
                self.client,
            )

        self.assertEqual(result.status, "sent", result)
        self.assertEqual(len(self.store.tool_audit.list(tool_name="multi_symbol_research")), before_multi)
        audits = self.store.tool_audit.list(tool_name="autonomous_learning_research")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[-1].request["arguments"].get("planned_action"), "RUN_OOS")
        self.assertEqual(audits[-1].request["arguments"].get("planned_action_reason"), "out_of_sample_blocker")
        mission = self.agent._brain._mission_for("telegram:100")
        self.assertEqual(mission.target_promotion_ready_candidates, 3)
        candidate = candidate_records(mission)[0]
        self.assertTrue(candidate_sample_exhausted(candidate))
        self.assertEqual(candidate.valid_symbols, 32)
        self.assertEqual(candidate.attempted_symbols, 33)
        self.assertEqual(candidate.trade_count, 201)
        response = self.client.sent[-1][1]
        self.assertIn("action_executed=RUN_OOS", response)
        self.assertNotIn("중복되지 않는 대표 종목을 추가", response)


if __name__ == "__main__":
    unittest.main()
