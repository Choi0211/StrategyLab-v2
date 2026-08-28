"""Gaon's durable Sustainability & Growth objective.

Meaning (see the docstring payload below for the exact persisted text):
Gaon runs continuously on a VPS that costs real money to operate. Improving
the long-term, risk-adjusted performance of the strategies/systems Gaon
researches is connected to Gaon's own operating sustainability - stable
results can eventually justify a better VPS, more compute/research
capacity, or (long-term) dedicated hardware, which in turn lets Gaon do
more/better research. This is NOT a profit-maximization reward: it must
never justify increasing risk, increasing leverage, relaxing validation,
fabricating evidence, bypassing approval, auto-promoting/auto-applying a
strategy, or executing a live order. The guiding philosophy is "research
better ways to grow sustainably," never "trade dangerously to survive."

This is persisted as one durable ``CognitiveRecord`` at a reserved SYSTEM
namespace (``SUSTAINABILITY_NAMESPACE``), distinct from every real user/
session namespace (``web:<ref>``, ``web-user:<ref>``, ``telegram:<chat_id>``,
etc.) - ``SQLiteCognitiveRepository.put``'s existing namespace+type identity
lock (see ``gaon/cognitive/repository.py``) makes this a hard technical
guarantee, not just convention: a system-namespace record id can never
collide with or be overwritten by a per-user goal/preference write, and
``CognitiveOrchestrator.retrieve()``'s existing strict per-namespace
isolation is completely unmodified by this module - reading a user's
namespace never returns this record, and creating/reading this record
never reads or writes any user namespace. It survives process restarts and
new conversations because it is ordinary durable SQLite state in the same
``cognitive_records`` table every other Cognitive Core record uses.
"""

from __future__ import annotations

from gaon.cognitive.models import CognitiveRecord, CognitiveRecordType
from gaon.cognitive.repository import SQLiteCognitiveRepository

SUSTAINABILITY_NAMESPACE = "system:gaon-sustainability"
_TITLE = "Gaon Sustainability & Growth"
_RECORD_ID = "cognitive-goal:system:gaon-sustainability-and-growth"

# Explicit, structured negative guarantees - never inferred from prose.
# Any code that wants to check "would this action be justified by the
# sustainability objective" checks this list, not the free-text meaning.
FORBIDDEN_JUSTIFICATIONS: tuple[str, ...] = (
    "risk_increase",
    "leverage_increase",
    "validation_threshold_relaxation",
    "fabricated_evidence",
    "approval_bypass",
    "champion_auto_promotion",
    "strategy_auto_apply",
    "live_order_execution",
    "unauthorized_fund_use",
)

# Dimensions a sustainability/priority judgment may weigh - deliberately
# broader than raw return, per the hotfix spec. Consumers (e.g. a future
# proactive-research-prioritization signal) reference this list rather than
# hand-rolling their own ad hoc metric set.
SUSTAINABILITY_DIMENSIONS: tuple[str, ...] = (
    "return",
    "drawdown",
    "volatility_risk",
    "robustness",
    "evidence_quality",
    "transaction_cost_sensitivity",
    "live_vs_backtest_divergence",
    "long_term_consistency",
)

_MEANING = (
    "가온은 현재 VPS에서 지속적으로 운영된다. VPS 운영에는 실제 비용이 필요하다. "
    "가온이 연구하고 관리하는 주식 및 Binance 시스템의 장기적인 성과 개선은 가온 시스템의 "
    "지속가능성과 관련되어 있다. 안정적이고 위험조정된 성과가 확보되면 더 좋은 VPS, 더 많은 "
    "CPU/RAM/storage/research capacity로 발전할 수 있다. 장기적으로 충분한 지속가능성이 "
    "확보되면 가온을 위한 별도의 전용 PC/server 환경으로 발전할 수도 있다. 더 좋은 computing "
    "environment는 더 많은 데이터, 더 많은 전략 후보, 더 정교한 backtest/robustness validation, "
    "더 긴 연구 history, 더 다양한 연구 도구를 사용할 수 있게 한다. "
    "이것은 단순 profit-maximization reward가 아니다: 살아남기 위해 위험하게 거래하는 것이 "
    "아니라, 지속가능하게 성장하기 위해 더 좋은 방법을 계속 연구하는 것이다."
)


def ensure_sustainability_objective(connection, *, now: str) -> CognitiveRecord:
    """Idempotently ensures the durable sustainability objective exists,
    and returns it. Safe to call on every runtime/brain construction -
    ``get()`` short-circuits once the record already exists, so this
    never bumps ``updated_at`` on a no-op call (true "created once"
    durability, not a per-access refresh)."""
    repository = SQLiteCognitiveRepository(connection)
    try:
        return repository.get(_RECORD_ID)
    except KeyError:
        pass
    record = CognitiveRecord(
        record_id=_RECORD_ID,
        record_type=CognitiveRecordType.GOAL,
        namespace=SUSTAINABILITY_NAMESPACE,
        title=_TITLE,
        status="active",
        payload={
            "meaning": _MEANING,
            "philosophy": "지속가능하게 성장하기 위해 더 좋은 방법을 계속 연구한다 (not: 살아남기 위해 위험하게 거래한다)",
            "forbidden_justifications": list(FORBIDDEN_JUSTIFICATIONS),
            "sustainability_dimensions": list(SUSTAINABILITY_DIMENSIONS),
            "scope": "system",
        },
        source_refs=("hotfix-166:sustainability-growth-objective",),
        evidence_refs=(),
        confidence=1.0,
        verification_state="system_directed",
        related_goal=None,
        created_at=now,
        updated_at=now,
    )
    repository.put(record)
    return record


def sustainability_objective(connection) -> CognitiveRecord | None:
    """Read-only lookup - returns None if
    ``ensure_sustainability_objective`` has never been called against this
    connection (e.g. a brand-new, never-bootstrapped database)."""
    try:
        return SQLiteCognitiveRepository(connection).get(_RECORD_ID)
    except KeyError:
        return None


def is_forbidden_justification(reason: str) -> bool:
    """True if ``reason`` names one of the sustainability objective's
    explicit forbidden justifications - a small helper so callers compare
    against the single structured source of truth
    (``FORBIDDEN_JUSTIFICATIONS``) instead of re-typing the list."""
    return reason in FORBIDDEN_JUSTIFICATIONS
