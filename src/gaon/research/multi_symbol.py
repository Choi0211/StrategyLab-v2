"""Autonomous multi-symbol KRX research for Sprint 141-150.

This module applies one user-provided strategy and one execution-assumption set
to an explicit or curated KRX universe. It records per-symbol evidence,
cross-symbol aggregation, concentration, sample sufficiency, candidate
generalization, and a deterministic Korean report. It is read-only: no orders,
no Champion promotion, and no strategy configuration mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import os
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.krx_real_pipeline import (
    BacktestExecutionAssumptionSet,
    CanonicalStrategySpec,
    EvidenceBasedStrategyCritic,
    ImprovementCandidate,
    ImprovementCandidateGenerator,
    KRXDatasetBuilder,
    KRXHistoricalDataProvider,
    RealBacktestResult,
    RealMarketDataUnavailable,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    WalkForwardValidator,
    _blocking_quality_findings,
    _findings_by_code,
    _json,
    _sha,
    build_market_data_provider_from_env,
    default_execution_assumptions,
    utc_now,
)
from gaon.research.real_research import DataQualityReport, DataQualityStatus, MarketDataset, MarketSymbol


MULTI_SYMBOL_SCHEMA_VERSION = 1
MULTI_SYMBOL_ARTIFACT_MARKERS = (
    "multi-symbol-research-release-check:",
    "telegram-multi-symbol-research-release-check:",
    "multi-symbol-research-demo:",
    "unit:",
    "integration:",
    "test:",
)

DEFAULT_CURATED_SYMBOLS = ("005930", "000660", "005380", "035420", "051910")
DEFAULT_REQUEST_TEXT = (
    "20일 고가 돌파, 종가 > MA20 > MA60, 거래량 20일 평균 이상, "
    "손절 -5%, 10일 저점 이탈 청산"
)


class UniverseType(str, Enum):
    EXPLICIT = "explicit"
    CURATED = "curated"


class ConcentrationDecision(str, Enum):
    BROAD = "broad"
    MODERATELY_CONCENTRATED = "moderately_concentrated"
    HIGHLY_CONCENTRATED = "highly_concentrated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CandidateGeneralizationDecision(str, Enum):
    ORIGINAL_PREFERRED = "original_preferred"
    CANDIDATE_PREFERRED = "candidate_preferred"
    NO_CLEAR_WINNER = "no_clear_winner"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class MultiSymbolBacktestRunner(Protocol):
    def run(self, run_id: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, *, generated_at: str | None = None) -> RealBacktestResult: ...


@dataclass(frozen=True)
class KRXResearchUniverse:
    universe_id: str
    universe_type: UniverseType
    symbols: tuple[str, ...]
    provenance: str
    fixture_backed: bool
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "universe_id": self.universe_id,
            "universe_type": self.universe_type.value,
            "symbols": list(self.symbols),
            "provenance": self.provenance,
            "fixture_backed": self.fixture_backed,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class MultiSymbolResearchRequest:
    run_id: str
    request_text: str
    universe: KRXResearchUniverse
    strategy_fingerprint: str
    assumptions_fingerprint: str
    period_start: str
    period_end: str
    provider: str
    source: str
    fixture_backed: bool
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "run_id": self.run_id,
            "request_text": self.request_text,
            "universe": self.universe.to_json(),
            "strategy_fingerprint": self.strategy_fingerprint,
            "assumptions_fingerprint": self.assumptions_fingerprint,
            "period": {"start": self.period_start, "end": self.period_end},
            "provider": self.provider,
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SymbolResearchEvidence:
    evidence_id: str
    symbol: str
    eligible: bool
    blocked_reason: str | None
    dataset_id: str | None
    dataset_fingerprint: str | None
    quality_status: str
    provider: str
    source: str
    fixture_backed: bool
    rows: int
    provider_gap_dates: tuple[str, ...]
    provider_ohlc_anomaly_dates: tuple[str, ...]
    provider_zero_volume_anomaly_dates: tuple[str, ...]
    blocking_findings: tuple[dict[str, object], ...]
    metrics: dict[str, object]
    backtest_result: RealBacktestResult | None
    warnings: tuple[str, ...]

    @property
    def trade_count(self) -> int:
        return int(self.metrics.get("trade_count", 0) or 0)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "symbol": self.symbol,
            "eligible": self.eligible,
            "blocked_reason": self.blocked_reason,
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "quality_status": self.quality_status,
            "provider": self.provider,
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "rows": self.rows,
            "provider_gap_dates": list(self.provider_gap_dates),
            "provider_ohlc_anomaly_dates": list(self.provider_ohlc_anomaly_dates),
            "provider_zero_volume_anomaly_dates": list(self.provider_zero_volume_anomaly_dates),
            "blocking_findings": list(self.blocking_findings),
            "metrics": dict(self.metrics),
            "backtest_result": self.backtest_result.to_json() if self.backtest_result else None,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class CandidateSymbolEvidence:
    candidate_id: str
    symbol: str
    eligible: bool
    metrics: dict[str, object]
    backtest_result: RealBacktestResult | None

    @property
    def trade_count(self) -> int:
        return int(self.metrics.get("trade_count", 0) or 0)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
            "eligible": self.eligible,
            "metrics": dict(self.metrics),
            "backtest_result": self.backtest_result.to_json() if self.backtest_result else None,
        }


@dataclass(frozen=True)
class UniverseResearchSummary:
    total_symbols: int
    eligible_symbols: int
    blocked_symbols: int
    symbols_with_trades: int
    aggregate_trade_count: int
    median_return: float | None
    median_mdd: float | None
    positive_return_symbol_ratio: float | None
    profitable_symbol_ratio: float | None
    trade_concentration: float | None
    return_concentration: float | None
    worst_symbol: str | None
    best_symbol: str | None
    concentration_decision: ConcentrationDecision
    sample_confidence: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "total_symbols": self.total_symbols,
            "eligible_symbols": self.eligible_symbols,
            "blocked_symbols": self.blocked_symbols,
            "symbols_with_trades": self.symbols_with_trades,
            "aggregate_trade_count": self.aggregate_trade_count,
            "median_return": self.median_return,
            "median_mdd": self.median_mdd,
            "positive_return_symbol_ratio": self.positive_return_symbol_ratio,
            "profitable_symbol_ratio": self.profitable_symbol_ratio,
            "trade_concentration": self.trade_concentration,
            "return_concentration": self.return_concentration,
            "worst_symbol": self.worst_symbol,
            "best_symbol": self.best_symbol,
            "concentration_decision": self.concentration_decision.value,
            "sample_confidence": self.sample_confidence,
        }


@dataclass(frozen=True)
class CandidateGeneralization:
    decision: CandidateGeneralizationDecision
    winner_id: str | None
    rows: tuple[dict[str, object], ...]
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "decision": self.decision.value,
            "winner_id": self.winner_id,
            "rows": [dict(row) for row in self.rows],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MultiSymbolResearchRun:
    run_id: str
    request: MultiSymbolResearchRequest
    strategy: CanonicalStrategySpec
    assumptions: BacktestExecutionAssumptionSet
    evidence: tuple[SymbolResearchEvidence, ...]
    candidate_evidence: tuple[CandidateSymbolEvidence, ...]
    summary: UniverseResearchSummary
    candidate_generalization: CandidateGeneralization
    final_recommendation: str
    korean_report: str
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
            "run_id": self.run_id,
            "request": self.request.to_json(),
            "strategy": self.strategy.to_json(),
            "assumptions": self.assumptions.to_json(),
            "evidence": [item.to_json() for item in self.evidence],
            "candidate_evidence": [item.to_json() for item in self.candidate_evidence],
            "summary": self.summary.to_json(),
            "candidate_generalization": self.candidate_generalization.to_json(),
            "final_recommendation": self.final_recommendation,
            "korean_report": self.korean_report,
            "generated_at": self.generated_at,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
            "approval_required_before_config_change": True,
        }


class KRXResearchUniverseResolver:
    def resolve(self, symbols: tuple[str, ...] | None = None, *, universe_type: str = "explicit", created_at: str | None = None) -> KRXResearchUniverse:
        at = created_at or utc_now()
        if symbols:
            normalized = _normalize_symbols(symbols)
            return KRXResearchUniverse(f"universe:explicit:{_sha({'symbols': normalized})[:12]}", UniverseType.EXPLICIT, normalized, "explicit_user_provided", False, at)
        if universe_type == "curated":
            return KRXResearchUniverse("universe:curated:krx-largecap-v1", UniverseType.CURATED, DEFAULT_CURATED_SYMBOLS, "curated_static_research_universe_v1", False, at)
        return KRXResearchUniverse(f"universe:explicit:{_sha({'symbols': DEFAULT_CURATED_SYMBOLS})[:12]}", UniverseType.EXPLICIT, DEFAULT_CURATED_SYMBOLS, "explicit_default_release_universe", False, at)


class SQLiteMultiSymbolResearchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_run(self, run: MultiSymbolResearchRun) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO multi_symbol_research_runs(
                    run_id, universe_id, status, recommendation, payload_json, generated_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run.run_id, run.request.universe.universe_id, "completed", run.final_recommendation, _json(run.to_json()), run.generated_at, run.request.source),
            )
            self._connection.execute(
                """
                INSERT OR REPLACE INTO multi_symbol_universe_snapshots(
                    universe_id, run_id, universe_type, symbols_json, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run.request.universe.universe_id, run.run_id, run.request.universe.universe_type.value, _json(list(run.request.universe.symbols)), _json(run.request.universe.to_json()), run.generated_at),
            )
            for item in run.evidence:
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO multi_symbol_symbol_evidence(
                        evidence_id, run_id, symbol, eligible, trade_count, quality_status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item.evidence_id, run.run_id, item.symbol, 1 if item.eligible else 0, item.trade_count, item.quality_status, _json(item.to_json()), run.generated_at),
                )
            for item in run.candidate_evidence:
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO multi_symbol_candidate_evidence(
                        evidence_id, run_id, candidate_id, symbol, eligible, trade_count, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"{run.run_id}:{item.candidate_id}:{item.symbol}", run.run_id, item.candidate_id, item.symbol, 1 if item.eligible else 0, item.trade_count, _json(item.to_json()), run.generated_at),
                )

    def get_payload(self, run_id: str, *, include_artifacts: bool = False) -> dict[str, object] | None:
        if not include_artifacts and _is_artifact(run_id):
            return None
        row = self._connection.execute("SELECT payload_json FROM multi_symbol_research_runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(str(row[0])) if row else None

    def list_runs(self, *, limit: int = 5, include_artifacts: bool = False) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            "SELECT run_id, status, recommendation, generated_at, source, payload_json FROM multi_symbol_research_runs ORDER BY generated_at DESC, run_id DESC"
        ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            run_id = str(row[0])
            if not include_artifacts and _is_artifact(run_id):
                continue
            payload = json.loads(str(row[5]))
            summary = dict(payload.get("summary", {}))
            results.append(
                {
                    "run_id": run_id,
                    "status": str(row[1]),
                    "recommendation": str(row[2]),
                    "generated_at": str(row[3]),
                    "source": str(row[4]),
                    "symbols": list(dict(payload.get("request", {})).get("universe", {}).get("symbols", [])),
                    "eligible_symbols": int(summary.get("eligible_symbols", 0) or 0),
                    "aggregate_trade_count": int(summary.get("aggregate_trade_count", 0) or 0),
                    "sample_confidence": str(summary.get("sample_confidence", "unknown")),
                    "concentration": str(summary.get("concentration_decision", "unknown")),
                }
            )
            if len(results) >= limit:
                break
        return tuple(results)

    def list_evidence(self, *, run_id: str | None = None, limit: int = 20, include_artifacts: bool = False) -> tuple[dict[str, object], ...]:
        if run_id is None:
            rows = self._connection.execute(
                "SELECT evidence_id, run_id, symbol, eligible, trade_count, quality_status, created_at, payload_json FROM multi_symbol_symbol_evidence ORDER BY created_at DESC, evidence_id DESC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT evidence_id, run_id, symbol, eligible, trade_count, quality_status, created_at, payload_json FROM multi_symbol_symbol_evidence WHERE run_id = ? ORDER BY created_at, evidence_id",
                (run_id,),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            rid = str(row[1])
            if not include_artifacts and _is_artifact(rid):
                continue
            payload = json.loads(str(row[7]))
            results.append(
                {
                    "evidence_id": str(row[0]),
                    "run_id": rid,
                    "symbol": str(row[2]),
                    "eligible": bool(row[3]),
                    "trade_count": int(row[4]),
                    "quality_status": str(row[5]),
                    "created_at": str(row[6]),
                    "provider_gap_dates": list(payload.get("provider_gap_dates", [])),
                    "blocking_findings": list(payload.get("blocking_findings", [])),
                    "metrics": dict(payload.get("metrics", {})),
                }
            )
            if len(results) >= limit:
                break
        return tuple(results)


class AutonomousMultiSymbolResearchOrchestrator:
    def __init__(self, connection: sqlite3.Connection | None = None, provider: KRXHistoricalDataProvider | None = None, runner: MultiSymbolBacktestRunner | None = None) -> None:
        self._connection = connection
        self._provider = provider or build_market_data_provider_from_env(os.environ)
        self._runner = runner or RuleBasedBacktestEngine()
        self._dataset_cache: dict[str, MarketDataset] = {}

    def run(
        self,
        request_text: str,
        *,
        symbols: tuple[str, ...] | None = None,
        universe_type: str = "explicit",
        start_date: str = "2021-07-25",
        end_date: str = "2026-07-24",
        run_id: str | None = None,
        generated_at: str | None = None,
    ) -> MultiSymbolResearchRun:
        at = generated_at or utc_now()
        rid = run_id or f"multi-symbol-research:{uuid4().hex}"
        universe = KRXResearchUniverseResolver().resolve(symbols, universe_type=universe_type, created_at=at)
        if not universe.symbols:
            raise RealMarketDataUnavailable("real_data_unavailable: universe has no symbols")
        strategy = UserStrategyParser().parse(request_text or DEFAULT_REQUEST_TEXT, symbol=universe.symbols[0], created_at=at)
        assumptions = default_execution_assumptions()
        evidence: list[SymbolResearchEvidence] = []
        self._dataset_cache = {}
        provider_name = getattr(self._provider, "source", "unknown")
        for symbol in universe.symbols:
            item = self._symbol_evidence(rid, request_text, symbol, start_date, end_date, strategy, assumptions, at)
            evidence.append(item)
        eligible_symbols = tuple(item.symbol for item in evidence if item.eligible and item.backtest_result is not None)
        candidate_results = self._candidate_evidence(rid, strategy, assumptions, tuple(evidence), at)
        summary = aggregate_symbol_evidence(tuple(evidence))
        generalization = compare_candidate_generalization(tuple(evidence), candidate_results)
        recommendation = _recommend(summary, generalization)
        any_real = any(item.source == "real" for item in evidence)
        request = MultiSymbolResearchRequest(
            rid,
            request_text,
            universe,
            strategy.fingerprint,
            _sha(assumptions.to_json()),
            start_date,
            end_date,
            provider_name,
            "real" if any_real else "fixture",
            any(item.fixture_backed for item in evidence),
            at,
        )
        report = render_multi_symbol_report(request, tuple(evidence), summary, generalization, recommendation)
        run = MultiSymbolResearchRun(rid, request, strategy, assumptions, tuple(evidence), candidate_results, summary, generalization, recommendation, report, at)
        if self._connection is not None:
            SQLiteMultiSymbolResearchRepository(self._connection).add_run(run)
        return run

    def _symbol_evidence(
        self,
        run_id: str,
        request_text: str,
        symbol: str,
        start_date: str,
        end_date: str,
        strategy: CanonicalStrategySpec,
        assumptions: BacktestExecutionAssumptionSet,
        at: str,
    ) -> SymbolResearchEvidence:
        try:
            dataset, quality, _inserted = KRXDatasetBuilder(self._connection, self._provider).build(symbol, start_date=start_date, end_date=end_date)
            self._dataset_cache[symbol.upper()] = dataset
            blocking = _blocking_quality_findings(quality)
            if blocking:
                return _blocked_symbol_evidence(run_id, symbol, dataset, quality, blocking, at)
            symbol_strategy = replace(strategy, spec_id=f"{strategy.spec_id}:{symbol}", symbol=symbol.upper(), created_at=at)
            result = self._runner.run(f"{run_id}:{symbol}:original", symbol_strategy, dataset, assumptions, generated_at=at)
            return SymbolResearchEvidence(
                f"{run_id}:evidence:{symbol.upper()}",
                symbol.upper(),
                True,
                None,
                dataset.dataset_id,
                dataset.fingerprint,
                quality.status.value,
                dataset.metadata.source,
                result.source.value,
                dataset.metadata.fixture_backed,
                len(dataset.bars),
                _finding_dates(_findings_by_code(quality, "provider_gap")),
                _finding_dates(_findings_by_code(quality, "provider_ohlc_anomaly")),
                _finding_dates(_findings_by_code(quality, "provider_zero_volume_anomaly")),
                (),
                result.metrics.to_json(),
                result,
                _quality_warnings(quality),
            )
        except Exception as exc:  # noqa: BLE001 - symbol failures are isolated and reported.
            return SymbolResearchEvidence(
                f"{run_id}:evidence:{symbol.upper()}",
                symbol.upper(),
                False,
                f"{exc.__class__.__name__}: {exc}",
                None,
                None,
                "fail",
                getattr(self._provider, "source", "unknown"),
                "unknown",
                False,
                0,
                (),
                (),
                (),
                ({"code": "provider_failure", "severity": "error", "message": str(exc)},),
                {"trade_count": 0},
                None,
                ("symbol failed; isolated from universe aggregation",),
            )

    def _candidate_evidence(
        self,
        run_id: str,
        strategy: CanonicalStrategySpec,
        assumptions: BacktestExecutionAssumptionSet,
        evidence: tuple[SymbolResearchEvidence, ...],
        at: str,
    ) -> tuple[CandidateSymbolEvidence, ...]:
        eligible = tuple(item for item in evidence if item.eligible and item.backtest_result is not None)
        if not eligible:
            return ()
        validation = WalkForwardValidator().validate(strategy, _dataset_from_backtest_stub(eligible[0].backtest_result), assumptions, run_id=f"{run_id}:candidate-seed", generated_at=at)
        findings = EvidenceBasedStrategyCritic().critique(strategy, eligible[0].backtest_result, validation)
        candidates = ImprovementCandidateGenerator().generate(strategy, findings, run_id=run_id, created_at=at)
        rows: list[CandidateSymbolEvidence] = []
        for candidate in candidates:
            for item in eligible:
                dataset = self._dataset_cache.get(item.symbol)
                if dataset is None:
                    continue
                candidate_strategy = replace(candidate.strategy, symbol=item.symbol, spec_id=f"{candidate.strategy.spec_id}:{item.symbol}")
                result = self._runner.run(f"{run_id}:{item.symbol}:{candidate.candidate_id}", candidate_strategy, dataset, assumptions, generated_at=at)
                rows.append(CandidateSymbolEvidence(candidate.candidate_id, item.symbol, True, result.metrics.to_json(), result))
        return tuple(rows)


def aggregate_symbol_evidence(evidence: tuple[SymbolResearchEvidence, ...]) -> UniverseResearchSummary:
    eligible = tuple(item for item in evidence if item.eligible)
    traded = tuple(item for item in eligible if item.trade_count > 0)
    returns = [float(item.metrics.get("total_return", 0.0) or 0.0) for item in traded]
    mdds = [float(item.metrics.get("mdd", 0.0) or 0.0) for item in traded]
    trades = [item.trade_count for item in traded]
    total_trades = sum(trades)
    positive_ratio = round(sum(1 for value in returns if value > 0) / len(returns), 6) if returns else None
    profitable_ratio = positive_ratio
    trade_concentration = round(max(trades) / total_trades, 6) if total_trades else None
    abs_returns = [abs(value) for value in returns]
    total_abs_return = sum(abs_returns)
    return_concentration = round(max(abs_returns) / total_abs_return, 6) if total_abs_return else None
    best = traded[returns.index(max(returns))].symbol if returns else None
    worst = traded[returns.index(min(returns))].symbol if returns else None
    concentration = _concentration_decision(len(traded), trade_concentration, return_concentration)
    sample_confidence = _sample_confidence(total_trades, len(traded), concentration, len(eligible), len(evidence))
    return UniverseResearchSummary(
        len(evidence),
        len(eligible),
        len(evidence) - len(eligible),
        len(traded),
        total_trades,
        _median(returns),
        _median(mdds),
        positive_ratio,
        profitable_ratio,
        trade_concentration,
        return_concentration,
        worst,
        best,
        concentration,
        sample_confidence,
    )


def compare_candidate_generalization(original: tuple[SymbolResearchEvidence, ...], candidates: tuple[CandidateSymbolEvidence, ...]) -> CandidateGeneralization:
    original_summary = aggregate_symbol_evidence(original)
    rows: list[dict[str, object]] = [
        {
            "candidate_id": "original",
            "aggregate_trade_count": original_summary.aggregate_trade_count,
            "median_return": original_summary.median_return,
            "median_mdd": original_summary.median_mdd,
            "profitable_symbol_ratio": original_summary.profitable_symbol_ratio,
            "symbols_with_trades": original_summary.symbols_with_trades,
            "concentration": original_summary.concentration_decision.value,
            "confidence": original_summary.sample_confidence,
        }
    ]
    grouped: dict[str, list[SymbolResearchEvidence]] = {}
    for item in candidates:
        grouped.setdefault(item.candidate_id, []).append(_candidate_as_symbol_evidence(item))
    for candidate_id in sorted(grouped):
        summary = aggregate_symbol_evidence(tuple(grouped[candidate_id]))
        rows.append(
            {
                "candidate_id": candidate_id,
                "aggregate_trade_count": summary.aggregate_trade_count,
                "median_return": summary.median_return,
                "median_mdd": summary.median_mdd,
                "profitable_symbol_ratio": summary.profitable_symbol_ratio,
                "symbols_with_trades": summary.symbols_with_trades,
                "concentration": summary.concentration_decision.value,
                "confidence": summary.sample_confidence,
            }
        )
    if original_summary.sample_confidence == "low":
        return CandidateGeneralization(CandidateGeneralizationDecision.NEEDS_MORE_EVIDENCE, None, tuple(rows), "cross-symbol sample confidence is low")
    eligible_rows = [row for row in rows if row["confidence"] != "low" and row["median_return"] is not None]
    if len(eligible_rows) < 2:
        return CandidateGeneralization(CandidateGeneralizationDecision.NEEDS_MORE_EVIDENCE, None, tuple(rows), "not enough eligible candidate evidence")
    best = max(eligible_rows, key=lambda row: (float(row["median_return"] or 0.0), int(row["aggregate_trade_count"] or 0)))
    original_row = rows[0]
    if best["candidate_id"] == "original":
        return CandidateGeneralization(CandidateGeneralizationDecision.ORIGINAL_PREFERRED, "original", tuple(rows), "original has the strongest generalized evidence")
    if float(best["median_return"] or 0.0) > float(original_row["median_return"] or 0.0) and int(best["symbols_with_trades"] or 0) >= int(original_row["symbols_with_trades"] or 0):
        return CandidateGeneralization(CandidateGeneralizationDecision.CANDIDATE_PREFERRED, str(best["candidate_id"]), tuple(rows), "tested candidate improves median return without reducing symbol breadth")
    return CandidateGeneralization(CandidateGeneralizationDecision.NO_CLEAR_WINNER, None, tuple(rows), "candidate evidence is mixed across symbols")


def render_multi_symbol_report(request: MultiSymbolResearchRequest, evidence: tuple[SymbolResearchEvidence, ...], summary: UniverseResearchSummary, generalization: CandidateGeneralization, recommendation: str) -> str:
    lines = [
        "[다중종목 실제 연구]",
        "",
        "[Universe]",
        f"- type={request.universe.universe_type.value}",
        f"- provenance={request.universe.provenance}",
        f"- symbols={len(request.universe.symbols)} ({', '.join(request.universe.symbols)})",
        f"- eligible={summary.eligible_symbols}",
        f"- blocked={summary.blocked_symbols}",
        "",
        "[전략]",
        f"- strategy_fingerprint={request.strategy_fingerprint}",
        f"- assumptions_fingerprint={request.assumptions_fingerprint}",
        f"- period={request.period_start}~{request.period_end}",
        f"- provider={request.provider}",
        f"- source={request.source}",
        f"- fixture_backed={str(request.fixture_backed).lower()}",
        "",
        "[종목별 결과]",
    ]
    for item in evidence:
        if item.eligible:
            lines.append(
                f"- {item.symbol}: eligible=true trades={item.trade_count} "
                f"return={item.metrics.get('total_return', 'unknown')} mdd={item.metrics.get('mdd', 'unknown')} "
                f"quality={item.quality_status} rows={item.rows}"
            )
            if item.provider_gap_dates:
                lines.append(f"  provider_gap_dates={','.join(item.provider_gap_dates)}")
            if item.provider_ohlc_anomaly_dates:
                lines.append(f"  provider_ohlc_anomaly_dates={','.join(item.provider_ohlc_anomaly_dates)}")
            if item.provider_zero_volume_anomaly_dates:
                lines.append(f"  provider_zero_volume_anomaly_dates={','.join(item.provider_zero_volume_anomaly_dates)}")
        else:
            lines.append(f"- {item.symbol}: eligible=false reason={item.blocked_reason or 'unknown'} quality={item.quality_status}")
    lines.extend(
        [
            "",
            "[전체 표본]",
            f"- aggregate_trade_count={summary.aggregate_trade_count}",
            f"- symbols_with_trades={summary.symbols_with_trades}",
            f"- sample_confidence={summary.sample_confidence}",
            "",
            "[일반화 분석]",
            f"- breadth={summary.symbols_with_trades}/{summary.eligible_symbols}",
            f"- concentration={summary.concentration_decision.value}",
            f"- trade_concentration={summary.trade_concentration}",
            f"- return_concentration={summary.return_concentration}",
            f"- best_symbol={summary.best_symbol}",
            f"- worst_symbol={summary.worst_symbol}",
            "",
            "[Original vs TESTED]",
        ]
    )
    for row in generalization.rows:
        lines.append(
            f"- {row['candidate_id']}: aggregate_trade_count={row['aggregate_trade_count']} "
            f"median_return={row['median_return']} median_mdd={row['median_mdd']} "
            f"profitable_symbol_ratio={row['profitable_symbol_ratio']} concentration={row['concentration']} confidence={row['confidence']}"
        )
    lines.extend(
        [
            "",
            "[가온의 판단]",
            f"- generalization={generalization.decision.value}",
            f"- recommendation={recommendation}",
            f"- reason={generalization.reason}",
            "",
            "[Safety]",
            "- 자동 주문 없음",
            "- Champion 자동 승격 없음",
            "- 승인 없는 config 변경 없음",
        ]
    )
    return "\n".join(lines)


def multi_symbol_research_payload(connection: sqlite3.Connection, request_text: str, *, symbols: tuple[str, ...] | None = None, universe_type: str = "explicit", start_date: str = "2021-07-25", end_date: str = "2026-07-24") -> dict[str, object]:
    run = AutonomousMultiSymbolResearchOrchestrator(connection, build_market_data_provider_from_env(os.environ)).run(request_text, symbols=symbols, universe_type=universe_type, start_date=start_date, end_date=end_date)
    return run.to_json()


def multi_symbol_research_status_payload(connection: sqlite3.Connection, *, limit: int = 5) -> dict[str, object]:
    runs = SQLiteMultiSymbolResearchRepository(connection).list_runs(limit=limit)
    return {"provider": "sqlite:multi_symbol_research", "runs": list(runs), "empty": not runs, "automatic_order": False, "automatic_champion_promotion": False, "automatic_config_apply": False}


def multi_symbol_research_history_payload(connection: sqlite3.Connection, *, run_id: str | None = None, limit: int = 20) -> dict[str, object]:
    evidence = SQLiteMultiSymbolResearchRepository(connection).list_evidence(run_id=run_id, limit=limit)
    return {"provider": "sqlite:multi_symbol_symbol_evidence", "evidence": list(evidence), "empty": not evidence, "automatic_order": False, "automatic_champion_promotion": False, "automatic_config_apply": False}


def multi_symbol_research_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    run = AutonomousMultiSymbolResearchOrchestrator(connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
        DEFAULT_REQUEST_TEXT,
        run_id=f"multi-symbol-research-release-check:{uuid4().hex}",
        symbols=DEFAULT_CURATED_SYMBOLS,
        start_date="2021-07-25",
        end_date="2026-07-24",
        generated_at=utc_now(),
    )
    if run.request.universe.universe_type is not UniverseType.EXPLICIT:
        raise RealMarketDataUnavailable("real_data_unavailable: release check did not use explicit universe")
    if run.request.strategy_fingerprint != run.strategy.fingerprint or run.request.assumptions_fingerprint != _sha(run.assumptions.to_json()):
        raise RealMarketDataUnavailable("real_data_unavailable: strategy/assumption fingerprint mismatch")
    if len(run.evidence) != 5 or run.summary.eligible_symbols < 5:
        raise RealMarketDataUnavailable("real_data_unavailable: per-symbol quality isolation failed")
    if run.summary.aggregate_trade_count <= 0 or not run.candidate_evidence:
        raise RealMarketDataUnavailable("real_data_unavailable: aggregation or candidate comparison failed")
    if run.to_json()["automatic_champion_promotion"] or run.to_json()["automatic_config_apply"]:
        raise RealMarketDataUnavailable("real_data_unavailable: safety boundary violated")
    return run.to_json()


def telegram_multi_symbol_research_release_check(connection: sqlite3.Connection, *, tool_executor_factory=None) -> dict[str, object]:
    from gaon.runtime.config import GaonRuntimeConfig
    from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
    from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry

    config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
    executor = tool_executor_factory(connection) if tool_executor_factory else SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection))
    from gaon.runtime.llm_conversation import SQLiteConversationRepository, SQLiteConversationToolResultRepository

    brain = LLMConversationBrain(config, SQLiteConversationRepository(connection), tool_executor=executor, tool_result_repository=SQLiteConversationToolResultRepository(connection))
    run_id = f"telegram-multi-symbol-research-release-check:{uuid4().hex}"
    request_text = "가온아 이 전략을 삼성전자, SK하이닉스, 현대차, NAVER, LG화학 실제 데이터에서 모두 검증해줘."
    response = brain.respond(LLMConversationRequest(run_id, "release-check", "telegram", request_text, utc_now(), f"{run_id}:message"))
    if response.route != "tool_read_only_authoritative" or "multi_symbol_research" not in response.tool_calls:
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol route was not authoritative")
    if "자동 주문 없음" not in response.text:
        raise RealMarketDataUnavailable("real_data_unavailable: deterministic safety report missing")
    audits = connection.execute("SELECT COUNT(*) FROM llm_tool_audit WHERE tool_name = 'multi_symbol_research'").fetchone()[0]
    return {"schema_version": 36, "run_id": run_id, "route": response.route, "tool_calls": list(response.tool_calls), "provider_calls": 0, "audit_count": int(audits)}


def _blocked_symbol_evidence(run_id: str, symbol: str, dataset: MarketDataset, quality: DataQualityReport, blocking: tuple[object, ...], at: str) -> SymbolResearchEvidence:
    return SymbolResearchEvidence(
        f"{run_id}:evidence:{symbol.upper()}",
        symbol.upper(),
        False,
        "blocking_data_quality",
        dataset.dataset_id,
        dataset.fingerprint,
        quality.status.value,
        dataset.metadata.source,
        "unknown",
        dataset.metadata.fixture_backed,
        len(dataset.bars),
        _finding_dates(_findings_by_code(quality, "provider_gap")),
        _finding_dates(_findings_by_code(quality, "provider_ohlc_anomaly")),
        _finding_dates(_findings_by_code(quality, "provider_zero_volume_anomaly")),
        tuple(item.to_json() for item in blocking),
        {"trade_count": 0},
        None,
        ("symbol excluded from aggregation because quality was blocking",),
    )


def _candidate_as_symbol_evidence(item: CandidateSymbolEvidence) -> SymbolResearchEvidence:
    return SymbolResearchEvidence(
        f"candidate:{item.candidate_id}:{item.symbol}",
        item.symbol,
        item.eligible,
        None if item.eligible else "candidate_unavailable",
        None,
        None,
        "pass",
        "candidate",
        "real" if item.backtest_result and item.backtest_result.source.value == "real" else "fixture",
        False,
        0,
        (),
        (),
        (),
        (),
        dict(item.metrics),
        item.backtest_result,
        (),
    )


def _dataset_from_backtest_stub(result: RealBacktestResult) -> MarketDataset:
    # The release-check runner only needs dataset identity and first/last bars.
    from gaon.research.real_research import MarketBar, MarketDataMetadata

    synthetic_bars = (
        MarketBar("2026-01-02", result.strategy.symbol, 100.0, 101.0, 99.0, 100.0, 1_000_000, 100_000_000),
        MarketBar("2026-07-24", result.strategy.symbol, 110.0, 111.0, 109.0, 110.0, 1_000_001, 110_000_000),
    )
    metadata = MarketDataMetadata(result.source.value, "KOSPI", "daily", synthetic_bars[0].timestamp, synthetic_bars[-1].timestamp, True, result.generated_at, result.source.value == "fixture")
    return MarketDataset(result.dataset_id, (MarketSymbol(result.strategy.symbol, result.strategy.symbol, "KOSPI"),), synthetic_bars, metadata)


def _normalize_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    normalized = []
    for symbol in symbols:
        value = str(symbol).strip().upper()
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _finding_dates(findings: tuple[object, ...]) -> tuple[str, ...]:
    dates: list[str] = []
    for finding in findings:
        message = getattr(finding, "message", "")
        for token in str(message).replace(",", " ").split():
            if len(token) == 10 and token[4] == "-" and token[7] == "-":
                dates.append(token)
    return tuple(sorted(dict.fromkeys(dates)))


def _quality_warnings(quality: DataQualityReport) -> tuple[str, ...]:
    return tuple(f"{finding.code}:{finding.message}" for finding in quality.findings if finding.severity != "error")


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 6)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 6)


def _concentration_decision(symbols_with_trades: int, trade_concentration: float | None, return_concentration: float | None) -> ConcentrationDecision:
    if symbols_with_trades < 2:
        return ConcentrationDecision.INSUFFICIENT_EVIDENCE
    max_concentration = max(value for value in (trade_concentration, return_concentration, 0.0) if value is not None)
    if max_concentration >= 0.65:
        return ConcentrationDecision.HIGHLY_CONCENTRATED
    if max_concentration >= 0.45:
        return ConcentrationDecision.MODERATELY_CONCENTRATED
    return ConcentrationDecision.BROAD


def _sample_confidence(total_trades: int, symbols_with_trades: int, concentration: ConcentrationDecision, eligible_symbols: int, total_symbols: int) -> str:
    if eligible_symbols < max(2, min(3, total_symbols)) or symbols_with_trades < 2 or total_trades < 20:
        return "low"
    if total_trades >= 60 and symbols_with_trades >= 4 and concentration is ConcentrationDecision.BROAD:
        return "high"
    if concentration is ConcentrationDecision.HIGHLY_CONCENTRATED:
        return "low"
    return "medium"


def _recommend(summary: UniverseResearchSummary, generalization: CandidateGeneralization) -> str:
    if summary.sample_confidence == "low":
        return "needs_more_evidence"
    if generalization.decision is CandidateGeneralizationDecision.CANDIDATE_PREFERRED:
        return "candidate_preferred"
    if generalization.decision is CandidateGeneralizationDecision.ORIGINAL_PREFERRED:
        return "original_preferred"
    return "no_clear_winner"


def _is_artifact(run_id: str) -> bool:
    return any(run_id.startswith(prefix) for prefix in MULTI_SYMBOL_ARTIFACT_MARKERS)

