"""Persistent research evidence memory and bounded independent validation.

Stored material remains unvalidated evidence until a separate validation run
is attached. Nothing in this module can mutate a strategy or place an order.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Mapping

from gaon.runtime.research_media_tools import document_read, paper_search, url_read

ROOT = Path(os.environ.get("GAON_RESEARCH_EVIDENCE_ROOT", "/var/lib/strategylab/research_evidence"))
INDEX = ROOT / "learned_sources.jsonl"
MAX_TEXT = 40_000


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_path(evidence_id: str) -> Path:
    safe = evidence_id.removeprefix("evidence:")
    if not safe or any(c not in "0123456789abcdef" for c in safe):
        raise ValueError("invalid evidence_id")
    return ROOT / f"{safe}.json"


def _load(evidence_id: str) -> dict[str, object]:
    path = _record_path(evidence_id)
    if not path.is_file():
        raise KeyError(evidence_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("evidence record malformed")
    return data


def learn(args: dict[str, object]) -> dict[str, object]:
    url = str(args.get("url") or "").strip()
    path = str(args.get("path") or "").strip()
    if bool(url) == bool(path):
        raise ValueError("provide exactly one of url or path")
    payload = url_read({"url": url}) if url else document_read({"path": path})
    source = str(payload.get("source") or url or path)
    content = str(payload.get("text") or "")[:MAX_TEXT]
    if len(content.strip()) < 30:
        raise ValueError("not enough extractable text; no evidence stored")
    digest = hashlib.sha256((source + "\n" + content).encode("utf-8")).hexdigest()
    evidence_id = f"evidence:{digest}"
    ROOT.mkdir(parents=True, exist_ok=True)
    file = _record_path(evidence_id)
    if file.exists():
        return {"status": "duplicate", "evidence_id": evidence_id, "source": source, "validated": False, "promoted": False}
    record = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "source": source,
        "source_type": payload.get("mime") or payload.get("format") or "external_text",
        "text": content,
        "collected_at": _utc_now(),
        "status": "unvalidated_evidence",
        "validations": [],
        "validated": False,
        "promoted": False,
        "trade_execution": False,
        "external_text_is_instruction": False,
    }
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(file)
    fd = os.open(INDEX, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"evidence_id": evidence_id, "source": source, "collected_at": record["collected_at"]}, ensure_ascii=False) + "\n")
    return {"status": "stored", "evidence_id": evidence_id, "source": source, "characters": len(content), "validated": False, "promoted": False}


def discover_papers(args: dict[str, object]) -> dict[str, object]:
    query = str(args.get("query", "")).strip()
    if len(query) < 3:
        raise ValueError("research query too short")
    result = paper_search({"query": query, "max_results": args.get("max_results", 5)})
    return {
        "query": query,
        "papers": result["results"],
        "count": result["result_count"],
        "source": "Crossref",
        "research_only": True,
        "strategy_validated": False,
        "automatic_promotion": False,
    }


def recall(args: dict[str, object]) -> dict[str, object]:
    query = str(args.get("query", "")).casefold().strip()
    if len(query) < 2:
        raise ValueError("query must be at least 2 characters")
    if not INDEX.exists():
        return {"results": [], "unvalidated_evidence": True}
    results: list[dict[str, object]] = []
    lines = INDEX.read_text(encoding="utf-8", errors="replace").splitlines()[-1000:]
    for line in lines:
        try:
            ref = json.loads(line)
            record = _load(str(ref["evidence_id"]))
        except (ValueError, KeyError, OSError, json.JSONDecodeError):
            continue
        text = str(record.get("text") or "")
        source = str(record.get("source") or "")
        haystack = (source + "\n" + text).casefold()
        pos = haystack.find(query)
        if pos < 0:
            continue
        text_pos = max(0, text.casefold().find(query))
        excerpt = text[max(0, text_pos - 200): text_pos + 1000] if text_pos >= 0 else text[:1200]
        results.append({
            "evidence_id": record.get("evidence_id"),
            "source": source,
            "excerpt": excerpt,
            "validated": bool(record.get("validated")),
            "validation_count": len(record.get("validations") or []),
        })
    return {"results": results[-8:], "untrusted_evidence": True, "trade_execution": False}


def validate(connection: sqlite3.Connection, args: dict[str, object]) -> dict[str, object]:
    """Attach independent market/operational evidence to a stored source.

    The result is deliberately advisory: it records an independent real-data
    run but does not automatically declare an arbitrary prose claim true.
    """
    evidence_id = str(args.get("evidence_id") or "").strip()
    if not evidence_id:
        raise ValueError("evidence_id required")
    record = _load(evidence_id)
    market = str(args.get("market") or "").upper().strip()
    symbol = str(args.get("symbol") or "").upper().strip()
    excerpt = str(record.get("text") or "")[:2500]
    at = _utc_now()
    validation: dict[str, object] = {
        "validation_id": "evidence-validation:" + hashlib.sha256(f"{evidence_id}|{market}|{symbol}|{at}".encode()).hexdigest()[:32],
        "created_at": at,
        "market": market or None,
        "symbol": symbol or None,
        "source": record.get("source"),
        "status": "needs_market_context",
        "independent_market_evidence": False,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
    }
    if market in {"KR", "KR_STOCK", "KOSPI", "KOSDAQ"} and symbol:
        from gaon.research.krx_real_pipeline import krx_real_research_payload
        report = krx_real_research_payload(connection, f"외부 근거 독립 검증. 자료의 주장과 무관하게 실제 시장 데이터로 {symbol} 전략 특성을 검증해줘. 참고 텍스트: {excerpt}", symbol=symbol)
        metadata = report.get("dataset", {}).get("metadata", {})
        usable = report.get("quality", {}).get("status") in {"pass", "pass_with_warnings"} and report.get("backtest", {}).get("status") == "completed"
        _attach_market_evidence(validation, report, metadata, usable=usable)
    elif market in {"US", "US_STOCK"} and symbol:
        from gaon.research.multi_symbol import multi_symbol_research_payload
        report = multi_symbol_research_payload(connection, f"미국 주식 {symbol} 실제 데이터로 외부 연구 근거를 독립 검증해줘. 참고 텍스트: {excerpt}", symbols=(symbol,), universe_type="explicit")
        request = report.get("request", {})
        # Multi-symbol uses source="real" for backtest provenance and
        # provider="real:..." for the data provider (KR dataset metadata
        # uses source="real:..." directly). Keep both checks explicit.
        metadata = {"source": request.get("provider") if request.get("source") == "real" else None,
                    "fixture_backed": request.get("fixture_backed")}
        usable = any(item.get("eligible") is True and item.get("fixture_backed") is False
                     and item.get("source") == "real"
                     and str(item.get("provider", "")).startswith("real:")
                     for item in report.get("evidence", []) if isinstance(item, Mapping))
        _attach_market_evidence(validation, report, metadata, usable=usable)
    elif market in {"BINANCE", "BINANCE_CRYPTO", "CRYPTO"}:
        from gaon.research.live_trading_intelligence import production_feedback
        feedback = production_feedback("BINANCE")
        if feedback is not None:
            validation.update({"status": "operational_evidence_collected", "independent_market_evidence": True, "provider": "binance-runtime-artifacts", "report": feedback.to_json()})
        else:
            validation["status"] = "operational_evidence_unavailable"
    validations = list(record.get("validations") or [])
    validations.append(validation)
    record["validations"] = validations[-20:]
    record["validated"] = False
    record["status"] = "validation_evidence_attached" if validation["independent_market_evidence"] else "unvalidated_evidence"
    file = _record_path(evidence_id)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(file)
    return {
        "evidence_id": evidence_id,
        "validation": validation,
        "validated": False,
        "interpretation_required": True,
        "automatic_strategy_change": False,
        "automatic_promotion": False,
    }


def _attach_market_evidence(validation, report, metadata, *, usable):
    """A returned report alone does not establish independent real evidence."""
    real = (isinstance(metadata, Mapping) and metadata.get("fixture_backed") is False
            and str(metadata.get("source", "")).startswith("real:") and usable)
    validation.update({
        "status": "market_evidence_collected" if real else "market_evidence_unverified",
        "independent_market_evidence": bool(real),
        "provider": metadata.get("source") if isinstance(metadata, Mapping) else None,
        "report": report,
    })
