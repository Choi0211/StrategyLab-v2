"""Gaon Final Integration Program - Step 1 integration acceptance.

Proves that a Research Director decision computed from the REAL Autonomous
Learning V2 production payload (gaon.knowledge.telegram_autonomous_learning)
is actually dispatched to the matching existing production engine, not a
duplicate engine, and that terminal actions never trigger further research.
"""

from __future__ import annotations

import contextlib
import sqlite3
import unittest
from unittest.mock import patch

from gaon.knowledge.research_director_bridge import (
    DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS,
    decide_next_research_action,
    execute_research_director_action,
)
from gaon.knowledge.telegram_autonomous_learning import (
    production_autonomous_learning_payload_from_baseline,
    telegram_autonomous_learning_payload,
)
from gaon.research.research_director import ResearchDirectorAction
from gaon.runtime.migrations import migrate


def _baseline(*, trades: int, symbols: int) -> dict[str, object]:
    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": "fp:candidate", "rules": ["breakout", "volume"]}
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
        "validation": {"symbols": symbols, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
        "backtest": {"source": "real", "metrics": {"trade_count": trades, "total_return": 0.12, "mdd": 0.08}},
        "candidates": [
            {
                "candidate_id": "candidate:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": "backtest:candidate",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": trades, "total_return": 0.13, "mdd": 0.07, "profit_factor": 1.4},
                },
            }
        ],
    }


class ResearchDirectorRealPayloadWiringTests(unittest.TestCase):
    """Uses the real production payload builder (no fixture research director)."""

    def test_real_payload_carries_a_research_director_decision(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        decision = payload["autonomous_learning_v2"]["research_director_decision"]
        self.assertIn(decision["action"], {item.value for item in ResearchDirectorAction})
        self.assertIsInstance(decision["reason"], str)
        self.assertTrue(decision["evidence_refs"])
        self.assertFalse(decision["strategy_mutated"])
        self.assertFalse(decision["order_executed"])
        self.assertFalse(decision["champion_promoted"])
        self.assertFalse(decision["approval_bypassed"])

    def test_no_external_evidence_recommends_collecting_more(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        decision = payload["autonomous_learning_v2"]["research_director_decision"]
        self.assertEqual(decision["action"], ResearchDirectorAction.COLLECT_MORE_EVIDENCE.value)

    def test_decision_recomputed_from_payload_matches_the_embedded_one(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        embedded = payload["autonomous_learning_v2"]["research_director_decision"]
        recomputed = decide_next_research_action(payload)
        self.assertEqual(embedded["action"], recomputed.action.value)
        self.assertEqual(embedded["stop_reason"], recomputed.stop_reason)


class ResearchDirectorActionActuallyRunsNextResearchTests(unittest.TestCase):
    """Proves the Director's decision is not just advisory text: dispatching
    it actually invokes the corresponding existing production engine."""

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        return connection

    def test_continuation_action_triggers_a_real_autonomous_learning_rerun(self) -> None:
        baseline = _baseline(trades=45, symbols=5)
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=baseline,
            external_research={"state": "content_unavailable"},
        )
        decision_json = payload["autonomous_learning_v2"]["research_director_decision"]
        self.assertEqual(decision_json["action"], ResearchDirectorAction.COLLECT_MORE_EVIDENCE.value)
        decision = decide_next_research_action(payload)

        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            migrate(connection)
            with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
                "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
                return_value={"state": "content_unavailable"},
            ):
                dispatch = execute_research_director_action(
                    decision,
                    connection=connection,
                    request_text="삼성전자 전략을 처음부터 다시 연구해줘",
                    symbol="005930",
                    steps_used=0,
                    max_steps=DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS,
                )

        self.assertEqual(dispatch["dispatched_tool"], "autonomous_learning_research")
        self.assertFalse(dispatch["terminal"])
        rerun = dispatch["result"]
        self.assertEqual(rerun["tool"], "autonomous_learning_research")
        self.assertFalse(rerun["strategy_mutated"])
        self.assertFalse(rerun["order_executed"])
        self.assertFalse(rerun["automatic_champion_promotion"])

    def test_expand_symbols_action_triggers_real_multi_symbol_research_not_a_duplicate_engine(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        decision = ResearchDirectorDecision(
            ResearchDirectorAction.EXPAND_SYMBOLS,
            "generalize across symbols",
            ("symbol_coverage_sufficient",),
            False,
            None,
        )
        connection = self._connection()
        sentinel = {"tool": "multi_symbol_research", "symbols": ["005930", "000660"], "strategy_mutated": False, "order_executed": False}
        with patch("gaon.research.multi_symbol.multi_symbol_research_payload", return_value=sentinel) as mocked:
            dispatch = execute_research_director_action(
                decision,
                connection=connection,
                request_text="다른 종목에도 일반화되는지 확인해봐",
                symbol="005930",
                additional_symbols=("000660",),
            )
        mocked.assert_called_once()
        called_args, called_kwargs = mocked.call_args
        self.assertEqual(called_kwargs.get("symbols") or called_args[2], ("005930", "000660"))
        self.assertEqual(dispatch["dispatched_tool"], "multi_symbol_research")
        self.assertEqual(dispatch["result"], sentinel)

    def test_hold_and_reject_never_call_any_research_engine(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        connection = self._connection()
        for action, stop_reason in (
            (ResearchDirectorAction.HOLD, "research_budget_exhausted"),
            (ResearchDirectorAction.REJECT_CANDIDATE, "candidate_rejected"),
        ):
            with self.subTest(action=action):
                decision = ResearchDirectorDecision(action, "terminal", ("steps_used", "max_steps"), True, stop_reason)
                with patch(
                    "gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload"
                ) as learning_mock, patch("gaon.research.multi_symbol.multi_symbol_research_payload") as multi_mock, patch(
                    "gaon.research.live_trading_intelligence.production_feedback"
                ) as live_mock:
                    dispatch = execute_research_director_action(
                        decision, connection=connection, request_text="Samsung", symbol="005930"
                    )
                learning_mock.assert_not_called()
                multi_mock.assert_not_called()
                live_mock.assert_not_called()
                self.assertIsNone(dispatch["dispatched_tool"])
                self.assertTrue(dispatch["terminal"])
                self.assertEqual(dispatch["stop_reason"], stop_reason)

    def test_human_review_recommendation_never_promotes_or_orders(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        decision = ResearchDirectorDecision(
            ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW,
            "fully validated",
            ("evidence_strength", "oos_completed"),
            True,
            "ready_for_human_review",
        )
        connection = self._connection()
        with patch("gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload") as mocked:
            dispatch = execute_research_director_action(
                decision, connection=connection, request_text="Samsung", symbol="005930"
            )
        mocked.assert_not_called()
        self.assertIsNone(dispatch["dispatched_tool"])
        self.assertTrue(dispatch["terminal"])
        self.assertFalse(dispatch["champion_promoted"])
        self.assertFalse(dispatch["order_executed"])


if __name__ == "__main__":
    unittest.main()
