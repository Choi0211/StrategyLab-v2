"""Telegram-facing Autonomous Learning V2 orchestration wrapper.

This module exposes the already-built Sprint 175-185 learning pipeline to the
read-only Telegram safe-tool boundary. It does not approve, mutate strategy
configuration, or place orders.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping


TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION = 1


def telegram_autonomous_learning_payload(
    connection: sqlite3.Connection,
    request_text: str,
    *,
    symbol: str = "005930",
    mode: str = "research",
) -> Mapping[str, object]:
    """Run the production-shaped autonomous learning route behind Telegram.

    The first stage is the existing authoritative KRX research path so the
    Telegram answer remains anchored to structured market evidence. The V2
    learning gate is then invoked through its existing deterministic E2E
    orchestration and stopped at the human approval boundary.
    """

    from gaon.research.krx_real_pipeline import krx_real_research_payload
    from .autonomous_learning_e2e import autonomous_learning_e2e_release_check

    baseline = krx_real_research_payload(connection, request_text, symbol=symbol)
    learning = dict(autonomous_learning_e2e_release_check())
    dataset = dict(baseline.get("dataset") or {})
    metadata = dict(dataset.get("metadata") or {})
    quality = dict(baseline.get("quality") or {})
    return {
        "schema_version": TELEGRAM_AUTONOMOUS_LEARNING_SCHEMA_VERSION,
        "tool": "autonomous_learning_research",
        "mode": mode,
        "symbol": symbol,
        "request_text": request_text,
        "baseline": baseline,
        "autonomous_learning_v2": learning,
        "selected_orchestration": "autonomous_learning_v2",
        "source": metadata.get("source") or baseline.get("source") or "unknown",
        "fixture_backed": bool(metadata.get("fixture_backed", baseline.get("fixture_backed", False))),
        "quality_status": quality.get("status", "unknown"),
        "approval_required": learning.get("promotion_status") == "requires_human_approval",
        "promotion_status": learning.get("promotion_status", "unknown"),
        "human_gate_status": learning.get("human_gate_status", "unknown"),
        "strategy_mutated": False,
        "order_executed": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
    }
