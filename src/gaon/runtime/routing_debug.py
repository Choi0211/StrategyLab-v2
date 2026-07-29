"""Read-only routing diagnostics for Telegram production messages."""

from __future__ import annotations

from hashlib import sha256
import unicodedata

from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.llm_conversation import _extract_date_range, _extract_krx_symbols
from gaon.runtime.llm_tool_routing import (
    _autonomous_retest,
    _autonomous_retest_ascii,
    _blocked,
    _krx_real_research,
    _multi_symbol_history,
    _multi_symbol_research_ascii,
    _multi_symbol_status,
    _normalize,
    route_read_only_tool,
)
from gaon.runtime.persona import safety_warning
from gaon.runtime.research_grounding import is_strict_real_research_tool


def telegram_routing_debug_payload(text: str) -> dict[str, object]:
    raw = text or ""
    normalized = _normalize(raw)
    intent = parse_intent(raw)
    selected_tool = route_read_only_tool(raw)
    safety = safety_warning(raw)
    authoritative = bool(selected_tool and is_strict_real_research_tool(selected_tool))
    generic_stock = intent is Intent.STOCK_ANALYSIS
    if authoritative:
        selected_route = "tool_read_only_authoritative"
        fallback_reason = None
        provider_allowed = False
    elif safety:
        selected_route = "rule_based"
        fallback_reason = "approval_boundary_or_safety_warning"
        provider_allowed = False
    elif generic_stock:
        selected_route = "rule_based"
        fallback_reason = "generic_stock_analysis_persona"
        provider_allowed = False
    elif selected_tool:
        selected_route = "tool_read_only"
        fallback_reason = None
        provider_allowed = False
    else:
        selected_route = "provider_or_rule_based"
        fallback_reason = "no_read_only_tool_route"
        provider_allowed = True
    start_date, end_date = _extract_date_range(raw)
    symbols = _extract_krx_symbols(raw)
    return {
        "raw_length": len(raw),
        "normalized_length": len(normalized),
        "sha256": sha256(raw.encode("utf-8")).hexdigest(),
        "unicode_normalization": "NFC" if unicodedata.is_normalized("NFC", raw) else "not_nfc",
        "first_100_chars": raw[:100],
        "last_100_chars": raw[-100:] if raw else "",
        "normalized_text": normalized,
        "parsed_intent": intent.value,
        "detected_symbols": list(symbols),
        "detected_dates": {"start": start_date, "end": end_date},
        "multi_symbol_evidence": {
            "history": _multi_symbol_history(normalized),
            "status": _multi_symbol_status(normalized),
            "research": _multi_symbol_research_ascii(normalized),
            "symbol_count": len(symbols),
        },
        "retest_evidence": {
            "ascii": _autonomous_retest_ascii(normalized),
            "legacy": _autonomous_retest(normalized),
        },
        "real_research_evidence": {"research": _krx_real_research(normalized)},
        "blocked": _blocked(normalized),
        "safety_warning": safety,
        "generic_stock_analysis": generic_stock,
        "selected_route": selected_route,
        "selected_tool": selected_tool,
        "authoritative": authoritative,
        "provider_allowed": provider_allowed,
        "fallback_reason": fallback_reason,
    }
