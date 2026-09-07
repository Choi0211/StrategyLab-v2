"""Tool capability abstraction.

A safe, read-only projection over the existing :class:`ToolRegistry`
(``gaon.runtime.llm_tools``). It answers two questions the conversational
layer needs:

* Is this registered tool backed by a real production provider, or is it a
  fixture / demo tool that must never be presented as a live data source?
* Which :class:`Capability` id does it correspond to?

The LLM never invents a tool name - it may only call tools the executor
already exposes - and this view additionally lets Gaon avoid offering a
fixture tool ("current weather", "web search") as if it were real.
"""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.gaon_agent.capabilities import (
    MARKET_DATA_READ,
    RESEARCH_MISSION_READ,
    STRATEGY_STATUS_READ,
    WEB_SEARCH,
)

# Registered tools that return fixture / normalized-demo payloads, not a
# live provider result. Gaon must disclose these as fixtures and must not
# use them to answer "what is X right now?".
FIXTURE_BACKED_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "news_search",
        "weather_current",
        "weather_forecast",
        "exchange_rate",
        "market_data",
        "strategy_critique",
        "strategy_quality_score",
        "research_candidate_compare",
        "backtest_strategy",
        "compare_backtests",
        "data_quality_check",
        "feature_discovery",
        "krx_market_data",
    }
)

# Tools that are genuinely wired to real data / real persisted state.
_PRODUCTION_GRADE_HINTS: frozenset[str] = frozenset(
    {
        "runtime_status",
        "champion_status",
        "v5_pipeline_history",
        "research_memory_search",
        "research_lineage",
        "market_data_status",
        "dataset_lookup",
        "backtest_result",
        "krx_real_research",
        "multi_symbol_research",
        "multi_symbol_research_status",
        "multi_symbol_research_history",
    }
)


@dataclass(frozen=True)
class ToolCapabilityView:
    name: str
    description: str
    risk_level: str
    production_grade: bool
    fixture_backed: bool
    capability_id: str | None


def _capability_for(name: str) -> str | None:
    if name in {"multi_symbol_research", "multi_symbol_research_status", "multi_symbol_research_history", "krx_real_research", "market_data_status", "dataset_lookup"}:
        return MARKET_DATA_READ
    if name in {"champion_status", "v5_pipeline_history", "research_lineage", "backtest_result"}:
        return STRATEGY_STATUS_READ
    if name in {"research_memory_search", "runtime_status"}:
        return RESEARCH_MISSION_READ
    if name in {"web_search", "news_search"}:
        return WEB_SEARCH
    return None


def tool_capability_views(registry) -> tuple[ToolCapabilityView, ...]:
    """Project every tool in a ``ToolRegistry`` to a :class:`ToolCapabilityView`."""
    views: list[ToolCapabilityView] = []
    for definition in registry.list():
        name = definition.name
        fixture = name in FIXTURE_BACKED_TOOLS
        production = name in _PRODUCTION_GRADE_HINTS and not fixture
        views.append(
            ToolCapabilityView(
                name=name,
                description=getattr(definition, "description", ""),
                risk_level=getattr(getattr(definition, "risk_level", None), "value", "read_only"),
                production_grade=production,
                fixture_backed=fixture,
                capability_id=_capability_for(name),
            )
        )
    return tuple(views)


def non_production_tool_names(registry) -> tuple[str, ...]:
    return tuple(view.name for view in tool_capability_views(registry) if not view.production_grade)
