"""Durable Gaon conversation-level market context (KR_STOCK / US_STOCK /
GLOBAL_STOCK / BINANCE_CRYPTO), shared by Web and Telegram.

Both transports call the exact same ``LLMConversationBrain.respond()`` (see
``docs/architecture/GaonBinanceConversationDashboardIntegration.md``), so
storing/reading this context in ONE place here - keyed off the same
``conversation_sessions.metadata_json`` column ``ResearchMission`` already
persists through - automatically gives both transports the same policy with
no second implementation.

This is deliberately a SIBLING key next to ``conversation_mvp`` (which
``gaon.knowledge.research_mission`` owns), not a new field on
``ResearchMission`` itself: ``ResearchMission.market`` is a KR-only field in
production today (every call site sets it to the literal string ``"KR"``),
already persisted and asserted on by existing tests/release-checks. Keeping
this context in its own key means adding Binance/US/global market awareness
cannot change what ``ResearchMission.market`` means or contains.
"""

from __future__ import annotations

from typing import Mapping

from gaon.research.global_market import GaonMarketContext

METADATA_KEY = "gaon_market_context"


def read_market_context(metadata: Mapping[str, object] | None) -> "GaonMarketContext | None":
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(METADATA_KEY)
    if not isinstance(raw, str):
        return None
    try:
        return GaonMarketContext(raw)
    except ValueError:
        return None


def store_market_context(metadata: Mapping[str, object] | None, context: "GaonMarketContext") -> dict[str, object]:
    """Returns a NEW metadata dict with ``context`` recorded - never mutates
    ``metadata`` in place, and never touches any other key (in particular,
    never touches ``conversation_mvp``/``research_mission``)."""
    updated = dict(metadata or {})
    updated[METADATA_KEY] = context.value
    return updated
