"""fix/rule-based-engine-fail-closed: an UnsupportedStrategySpecError from
RuleBasedBacktestEngine must fail the WHOLE research/deep-validation path
closed - never swallowed, never turned into a valid-looking (empty or
partial) backtest result, never counted as candidate robustness evidence,
never promotion-ready.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    DEFAULT_KR_EXCHANGES,
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    record_focus_symbol,
)
from gaon.knowledge.strategy_candidate import new_candidate, record_breadth_progress
from gaon.research.krx_real_pipeline import (
    ProvenancedValue,
    FieldProvenance,
    RealAutonomousResearchPipeline,
    UnsupportedStrategySpecError,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

NOW = "2026-09-05T00:00:00Z"


def _unsupported_spec_rules() -> dict:
    # A real, supported breakout family's rules + one rule the engine does
    # not implement. Pre-fix the engine silently dropped the extra rule and
    # ran a plain breakout.
    return {
        "entry": {
            "breakout_lookback": {"value": 20, "provenance": "research_candidate"},
            "rsi_below": {"value": 30, "provenance": "research_candidate"},
        },
        "exit": {
            "protective_stop_pct": {"value": -5.0, "provenance": "research_candidate"},
            "channel_exit_lookback": {"value": 10, "provenance": "research_candidate"},
        },
        "filters": {},
    }


class PipelineFailsClosedTests(unittest.TestCase):
    def test_real_autonomous_research_pipeline_raises_not_returns_a_report(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            RealAutonomousResearchPipeline(None).run(
                "005930 test", symbol="005930", candidate_spec=_unsupported_spec_rules(), generated_at=NOW
            )


class CandidateDeepValidationFailsClosedTests(unittest.TestCase):
    """End to end through the real production stack: a candidate whose
    spec_rules carry an engine-unsupported rule must not produce robustness
    evidence, must not become promotion-ready, must not fabricate a
    backtest result, and must not touch any trading/approval/promotion
    surface."""

    def test_unsupported_candidate_spec_records_no_evidence_and_is_not_promoted(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = GaonRuntimeConfig(telegram_allowed_chat_ids=("100",), assistant_enabled=True, assistant_provider="deterministic")
            agent = TelegramConversationAgent(config, store._connection)
            runtime = TelegramRuntime(agent, allowed_chat_ids=("100",))

            candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
            candidate = record_breadth_progress(
                candidate, attempted=5, valid=5, trade_count=81,
                evidence_symbols=("286940", "005930", "000660", "005380", "035420"),
                excluded_symbols=(), provider_blocked=False, now=NOW,
            )
            # Corrupt only spec_rules: add an engine-unsupported entry rule.
            corrupted = replace(candidate, spec_rules={
                "entry": {**dict(candidate.spec_rules["entry"]), "rsi_below": {"value": 30, "provenance": "research_candidate"}},
                "exit": dict(candidate.spec_rules["exit"]),
                "filters": dict(candidate.spec_rules["filters"]),
            })
            mission = ResearchMission(
                mission_id="research-mission:engine-capability-test",
                market="KR", universe_scope=MissionUniverseScope.MARKET_WIDE, symbols=(),
                exchanges=DEFAULT_KR_EXCHANGES, strategy_family="short_term_daytrade",
                improve_return=True, improve_safety=True, baseline_comparison="registered_strategy",
                target_promotion_ready_candidates=3, current_promotion_ready_candidates=0,
                promotion_ready_candidates=(), explored_symbols=(), status=MissionStatus.ACTIVE,
                blocked_reason=None, cycles_completed=1, created_at=NOW, updated_at=NOW,
                originating_request="test", candidates=(corrupted.to_json(),),
                active_candidate_id=corrupted.candidate_id,
            )
            mission = record_focus_symbol(mission, symbol="005930", now=NOW)
            seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "안녕하세요", NOW, "telegram:100:0")
            agent._brain.respond(seed)
            agent._brain._remember_mission(seed, mission)

            response = agent._brain.respond(
                LLMConversationRequest("telegram:100", "telegram:100", "telegram", "연구를 계속해주세요", NOW, "telegram:100:1")
            )

            # Fail-closed: a research-failure route, not a normal cycle result.
            self.assertTrue(response.route.startswith("research_failure_"), response.route)
            self.assertIn("engine_capability", response.route)
            self.assertTrue(
                any("engine_capability" in w for w in response.warnings),
                response.warnings,
            )

            updated_mission = agent._brain._mission_for("telegram:100")
            updated_candidate = next(c for c in updated_mission.candidates if c["candidate_id"] == corrupted.candidate_id)
            # No robustness evidence recorded, not promotion-ready, mission
            # not marked with any promotion-ready candidate.
            self.assertEqual(updated_candidate.get("validation_stage_status", {}), {})
            self.assertEqual(updated_candidate.get("robustness_evidence_symbols", []), [])
            self.assertNotEqual(updated_candidate.get("status"), "promotion_ready")
            self.assertEqual(updated_mission.current_promotion_ready_candidates, 0)
            self.assertEqual(updated_mission.promotion_ready_candidates, ())
        finally:
            store.close()

    def test_no_trading_or_promotion_or_approval_side_effects(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = GaonRuntimeConfig(telegram_allowed_chat_ids=("100",), assistant_enabled=True, assistant_provider="deterministic")
            agent = TelegramConversationAgent(config, store._connection)
            candidate = new_candidate("breakout_standard", sequence=1, now=NOW)
            candidate = record_breadth_progress(
                candidate, attempted=5, valid=5, trade_count=81,
                evidence_symbols=("286940", "005930", "000660", "005380", "035420"),
                excluded_symbols=(), provider_blocked=False, now=NOW,
            )
            corrupted = replace(candidate, spec_rules={
                "entry": {**dict(candidate.spec_rules["entry"]), "rsi_below": {"value": 30, "provenance": "research_candidate"}},
                "exit": dict(candidate.spec_rules["exit"]),
                "filters": dict(candidate.spec_rules["filters"]),
            })
            mission = ResearchMission(
                mission_id="research-mission:engine-capability-safety",
                market="KR", universe_scope=MissionUniverseScope.MARKET_WIDE, symbols=(),
                exchanges=DEFAULT_KR_EXCHANGES, strategy_family="short_term_daytrade",
                improve_return=True, improve_safety=True, baseline_comparison="registered_strategy",
                target_promotion_ready_candidates=3, current_promotion_ready_candidates=0,
                promotion_ready_candidates=(), explored_symbols=(), status=MissionStatus.ACTIVE,
                blocked_reason=None, cycles_completed=1, created_at=NOW, updated_at=NOW,
                originating_request="test", candidates=(corrupted.to_json(),),
                active_candidate_id=corrupted.candidate_id,
            )
            mission = record_focus_symbol(mission, symbol="005930", now=NOW)
            seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "안녕하세요", NOW, "telegram:100:0")
            agent._brain.respond(seed)
            agent._brain._remember_mission(seed, mission)

            audit_before = len(store.tool_audit.list())
            agent._brain.respond(
                LLMConversationRequest("telegram:100", "telegram:100", "telegram", "연구를 계속해주세요", NOW, "telegram:100:1")
            )

            # The only research tool that ran was the read-only autonomous
            # learning attempt, and it was denied - no order/promotion tool.
            for record in store.tool_audit.list()[audit_before:]:
                self.assertIn(record.tool_name, {"autonomous_learning_research", "multi_symbol_research"})
                if record.tool_name == "autonomous_learning_research":
                    self.assertEqual(record.status, "denied")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
