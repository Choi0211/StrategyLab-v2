from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import sqlite3
import unittest

from gaon.knowledge.strategy_candidate import (
    StrategyCandidateStatus,
    _rank_templates_by_learning,
    mark_promotion_ready,
    mark_rejected,
    new_candidate,
    next_untried_family,
    record_breadth_progress,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
)
from gaon.learning.contracts import LearningRecordType
from gaon.learning.production import ProductionLearningEngine, SQLiteLearningRepository
from gaon.runtime.llm_tools import SafeToolExecutor, _research_memory_search, default_tool_registry
from gaon.runtime.llm_conversation import (
    LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository, _default_tool_arguments,
)
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.config import GaonRuntimeConfig

NOW = "2026-10-18T00:00:00Z"
LATER = "2026-10-19T00:00:00Z"


def _mission(mission_id: str = "research-mission:learning-v3", market: str = "KR"):
    return SimpleNamespace(mission_id=mission_id, market=market)


def _with_evidence(candidate, *, start: int = 0, count: int = 5, positive: bool = True, now: str = NOW):
    details = {}
    for offset in range(count):
        index = start + offset
        symbol = f"{index+1:06d}"
        total_return = 0.08 + index * 0.001 if positive else -0.08 - index * 0.001
        details[symbol] = {
            "symbol": symbol,
            "eligible": True,
            "trade_count": 5,
            "metrics": {"trade_count": 5, "total_return": total_return, "mdd": 0.08},
            "evidence_id": f"multi:evidence:{symbol}",
            "source": "real:yahoo-chart",
            "fixture_backed": False,
        }
    return record_breadth_progress(
        candidate,
        attempted=count,
        valid=count,
        trade_count=count * 5,
        evidence_symbols=tuple(details),
        excluded_symbols=(),
        provider_blocked=False,
        now=now,
        evidence_details=details,
        breadth_summary={"sample_confidence": "medium"},
    )


class ProductionLearningV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.engine = ProductionLearningEngine(self.connection)

    def test_schema_v44_adds_durable_learning_tables(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 44)
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("learning_records", tables)
        self.assertIn("learning_record_versions", tables)
        self.assertIn("learning_audit_events", tables)

    def test_candidate_learning_is_versioned_and_unchanged_state_is_noop(self) -> None:
        candidate = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW))
        first = self.engine.learn_candidate(_mission(), candidate, now=NOW)
        duplicate = self.engine.learn_candidate(_mission(), candidate, now=NOW)
        candidate2 = _with_evidence(candidate, start=5, count=2, now=LATER)
        second = self.engine.learn_candidate(_mission(), candidate2, now=LATER)

        self.assertTrue(first.written)
        self.assertFalse(duplicate.written)
        self.assertTrue(second.written)
        self.assertEqual(second.version, 2)
        versions = self.connection.execute(
            "SELECT version FROM learning_record_versions WHERE record_id=? ORDER BY version",
            (second.record_id,),
        ).fetchall()
        self.assertEqual(versions, [(1,), (2,)])
        self.assertEqual(len(SQLiteLearningRepository(self.connection).list_audit(second.record_id)), 2)

    def test_only_promotion_ready_is_success_pattern(self) -> None:
        candidate = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW), count=20)
        ordinary = self.engine.learn_candidate(_mission(), candidate, now=NOW)
        self.assertEqual(ordinary.record_type, LearningRecordType.RESEARCH_OUTCOME.value)

        ready = mark_promotion_ready(candidate, now=LATER)
        promoted = self.engine.learn_candidate(_mission(), ready, now=LATER)
        self.assertEqual(promoted.record_type, LearningRecordType.SUCCESS_PATTERN.value)

    def test_rejection_becomes_failure_pattern_and_conflict_penalty_is_preserved(self) -> None:
        positive = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW), count=20)
        positive = mark_promotion_ready(positive, now=NOW)
        self.engine.learn_candidate(_mission("mission:positive"), positive, now=NOW)

        negative = _with_evidence(new_candidate("breakout_standard", sequence=2, now=NOW), count=20, positive=False)
        negative = mark_rejected(negative, reason="economic_viability_failed:test", now=LATER)
        result = self.engine.learn_candidate(_mission("mission:negative"), negative, now=LATER)

        self.assertEqual(result.record_type, LearningRecordType.FAILURE_PATTERN.value)
        self.assertGreater(result.conflict_penalty or 0.0, 0.0)
        record = SQLiteLearningRepository(self.connection).get(result.record_id)
        self.assertGreater(record.confidence.conflict_penalty, 0.0)
        self.assertEqual(record.confidence.validation_state, "need_validation")

    def test_family_priors_are_advisory_and_can_reorder_untried_families(self) -> None:
        preferences = {"breakout_volume_confirmed": 0.8, "breakout_standard": -0.6}
        picked = next_untried_family((), family_preferences=preferences)
        self.assertEqual(picked, "breakout_volume_confirmed")

        ordered = _rank_templates_by_learning(
            NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
            {"volatility_thrust_standard": 0.9, "mean_reversion_standard": -0.4},
        )
        self.assertEqual(ordered[0].family, "volatility_thrust_standard")
        self.assertEqual({item.family for item in ordered}, {item.family for item in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES})

    def test_operational_feedback_updates_cost_lesson_without_claiming_model_match(self) -> None:
        feedback = SimpleNamespace(to_json=lambda: {
            "market": "BINANCE",
            "completed_trade_count": 47,
            "commission_observation_count": 192,
            "observed_commission_rate": 0.000448,
            "slippage_observation_count": 0,
            "partial_fill_count": 19,
            "total_realized_pnl": -12.3,
        })
        result = self.engine.sync_operational_feedback(feedback, now=NOW)
        self.assertTrue(result.written)
        record = SQLiteLearningRepository(self.connection).get("learning:operational:BINANCE:execution-cost")
        self.assertIn("cost_model_match=unconfirmed", record.content)
        self.assertLessEqual(record.confidence.value, 0.72)
        self.assertFalse(record.confidence.can_approve)

    def test_strategy_attributed_operational_feedback_creates_observational_runtime_memory_only(self) -> None:
        feedback = SimpleNamespace(to_json=lambda: {
            "market": "BINANCE",
            "completed_trade_count": 47,
            "commission_observation_count": 192,
            "observed_commission_rate": 0.000448,
            "slippage_observation_count": 0,
            "partial_fill_count": 19,
            "total_realized_pnl": -12.3,
            "strategy_identity_observation_count": 20,
            "strategy_identity_total_count": 40,
            "strategy_performance": [{
                "mode":"paper", "strategy_id":"flow_rsi30", "completed_trade_count":20,
                "win_rate":0.55, "total_realized_pnl":1.25, "net_pnl_observation_count":5,
                "observed_net_pnl_total":0.8, "fee_observation_count":5, "observed_fee_total":-0.2,
                "long_trade_count":12, "short_trade_count":8,
                "first_closed_at":"2026-10-01T00:00:00Z", "last_closed_at":"2026-10-17T00:00:00Z",
                "evidence_refs":["binance-archive:paper:e1","binance-archive:paper:e2"],
            }],
        })
        self.engine.sync_operational_feedback(feedback, now=NOW)
        records = SQLiteLearningRepository(self.connection).filter(market="BINANCE", strategy="runtime:paper:flow_rsi30")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.record_type, LearningRecordType.RESEARCH_OUTCOME)
        self.assertIn("inference_scope=observational_only", record.content)
        self.assertIn("completed_trades=20", record.content)
        self.assertEqual(record.revalidation.frequency, "weekly")
        self.assertEqual(record.confidence.validation_state, "paper_observed")
        self.assertLessEqual(record.confidence.value, 0.72)
        self.assertFalse(record.confidence.can_approve)
        # Runtime strategy telemetry is never a research-family prior.
        self.assertEqual(self.engine.family_priors(market="BINANCE"), {})

    def test_strategy_operational_memory_versions_only_when_material_observation_changes(self) -> None:
        state = {"count": 12, "pnl": -2.0, "refs": ["binance-archive:paper:e1"]}
        feedback = SimpleNamespace(to_json=lambda: {
            "market":"BINANCE", "completed_trade_count":12, "commission_observation_count":0,
            "slippage_observation_count":0, "partial_fill_count":0, "total_realized_pnl":state["pnl"],
            "strategy_identity_observation_count":state["count"], "strategy_identity_total_count":state["count"],
            "strategy_performance":[{
                "mode":"paper","strategy_id":"flow_btc_bear_relvol25",
                "completed_trade_count":state["count"],"win_rate":0.25,"total_realized_pnl":state["pnl"],
                "net_pnl_observation_count":0,"fee_observation_count":0,
                "long_trade_count":state["count"],"short_trade_count":0,
                "first_closed_at":"2026-10-10T00:00:00Z","last_closed_at":"2026-10-17T00:00:00Z",
                "evidence_refs":list(state["refs"]),
            }],
        })
        self.engine.sync_operational_feedback(feedback, now=NOW)
        self.engine.sync_operational_feedback(feedback, now=NOW)
        record = SQLiteLearningRepository(self.connection).filter(
            market="BINANCE", strategy="runtime:paper:flow_btc_bear_relvol25"
        )[0]
        self.assertEqual(record.version, 1)
        state["count"] = 13; state["pnl"] = -2.5; state["refs"].append("binance-archive:paper:e2")
        self.engine.sync_operational_feedback(feedback, now=LATER)
        record = SQLiteLearningRepository(self.connection).filter(
            market="BINANCE", strategy="runtime:paper:flow_btc_bear_relvol25"
        )[0]
        self.assertEqual(record.version, 2)

    def test_generic_learning_query_returns_recent_learning_v3_records(self) -> None:
        candidate = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW))
        self.engine.learn_candidate(_mission(), candidate, now=NOW)
        payload = _research_memory_search(self.connection, {"query": "지금까지 무엇을 배웠어?"})
        self.assertTrue(any(item.get("timeframe") == "learning_v3" for item in payload["results"]))

    def test_memory_tool_arguments_capture_named_strategy_family(self) -> None:
        args = _default_tool_arguments("research_memory_search", "평균회귀에서 배운 점 알려줘")
        self.assertEqual(args.get("strategy_family"), "mean_reversion_standard")

    def test_end_to_end_what_learned_question_reads_durable_memory_without_recent_context(self) -> None:
        candidate = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW))
        self.engine.learn_candidate(_mission(), candidate, now=NOW)
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
        )
        response = brain.respond(LLMConversationRequest(
            session_id="telegram:learning-v3", user_ref="user:learning-v3", source="telegram",
            text="지금까지 뭘 배웠어?", received_at=LATER, message_id="message:learning-v3",
        ))
        self.assertEqual(response.route, "tool_read_only")
        self.assertEqual(response.tool_calls, ("research_memory_search",))
        self.assertIn("저장된 학습 기록", response.text)
        self.assertIn("경제성=", response.text)
        self.assertIn("Confidence", response.text)
        self.assertNotIn("autonomous_learning_research", response.tool_calls)

    def test_existing_research_memory_search_includes_learning_v3(self) -> None:
        candidate = _with_evidence(new_candidate("breakout_standard", sequence=1, now=NOW))
        self.engine.learn_candidate(_mission(), candidate, now=NOW)
        payload = _research_memory_search(self.connection, {"strategy_family": "breakout_standard"})
        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(any(item.get("timeframe") == "learning_v3" for item in payload["results"]))
        self.assertFalse(payload["automatic_promotion"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])


if __name__ == "__main__":
    unittest.main()
