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
import re
import sqlite3
from typing import Mapping, Protocol
from uuid import uuid4

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.krx_real_pipeline import (
    BacktestExecutionAssumptionSet,
    CanonicalStrategySpec,
    EvidenceBasedStrategyCritic,
    FieldProvenance,
    ImprovementCandidate,
    ImprovementCandidateGenerator,
    KRXDatasetBuilder,
    KRXHistoricalDataProvider,
    ProvenancedValue,
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
from gaon.research.real_research import (
    DataQualityEngine, DataQualityFinding, DataQualityReport, DataQualityStatus, MarketDataProvider,
    MarketDataset, MarketSymbol, SQLiteDatasetRegistry,
)
from gaon.research.krx_universe import KRXUniverseResult
from gaon.research.global_market import (
    GlobalMarketDataProvider, MarketScope, resolve_market_scope,
    research_sample_size, select_bounded_universe,
)
from gaon.research.live_trading_intelligence import (
    adaptive_budget, adaptive_batches, production_feedback, live_report_lines,
)


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
PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT = """가온아 아래 5개 종목의 실제 KRX 데이터를 사용해서 이 전략이 여러 종목에서도 일반적으로 유효한지 다중종목 연구해줘.

대상 종목:
005930 삼성전자
000660 SK하이닉스
005380 현대차
035420 NAVER
051910 LG화학

연구 기간:
2021-07-25 ~ 2026-07-24

전략:
20일 고가 돌파
종가 > MA20 > MA60
거래량 20일 평균 이상
손절 -5%
10일 저점 이탈 청산

모든 종목에 동일한 전략과 동일한 백테스트 가정을 적용해줘.

각 종목별로 실제 데이터 날짜, 거래 횟수, 수익률, MDD, Profit Factor, 승률을 기록해줘.

그리고 전체 5종목을 종합해서 총 거래 표본, 거래가 발생한 종목 수, 수익 종목 비율, median return, median MDD, 종목별 성과 집중도, 특정 종목 의존 여부, 전략의 cross-symbol robustness를 분석해줘.

원본 전략과 TESTED 개선 후보 A/B/C를 동일한 5종목에서 비교해서 어떤 후보가 여러 종목에 가장 잘 일반화되는지 판단해줘.

마지막에는 sample confidence, concentration 판단, generalization 판단, 최종 recommendation을 구조화된 실제 연구 결과만 기준으로 알려줘.

검증되지 않은 숫자나 조건은 만들지 말고 자동 주문, Champion 자동 승격, 승인 없는 config 변경은 하지 마."""


def _strategy_from_candidate_spec(candidate_spec: Mapping[str, object], *, symbol: str, created_at: str) -> CanonicalStrategySpec:
    """Reconstructs a CanonicalStrategySpec from the JSON-safe rules-only
    shape ``gaon.knowledge.strategy_candidate.spec_rules_to_json`` produces
    (``{"entry": {...}, "exit": {...}, "filters": {...}}``, each value in
    ``ProvenancedValue.to_json()`` shape). Patch 8.2: lets a mission-driven
    research cycle evaluate ONE strategy candidate's exact rules across a
    symbol universe, instead of ``UserStrategyParser`` re-parsing (and
    potentially re-interpreting) free text on every call."""

    def _field(raw: Mapping[str, object]) -> ProvenancedValue:
        return ProvenancedValue(raw["value"], FieldProvenance(str(raw.get("provenance", FieldProvenance.RESEARCH_CANDIDATE.value))))

    entry = {key: _field(value) for key, value in dict(candidate_spec.get("entry") or {}).items()}
    exit_rules = {key: _field(value) for key, value in dict(candidate_spec.get("exit") or {}).items()}
    filters = {key: _field(value) for key, value in dict(candidate_spec.get("filters") or {}).items()}
    return CanonicalStrategySpec(
        spec_id=f"candidate-spec:{_sha(dict(candidate_spec))[:16]}",
        symbol=symbol.upper(),
        entry=entry,
        exit=exit_rules,
        filters=filters,
        source_text="strategy-candidate:multi-symbol-evaluation",
        created_at=created_at,
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
    """Backward-compatible name for the market-agnostic research universe."""
    universe_id: str
    universe_type: UniverseType
    symbols: tuple[str, ...]
    provenance: str
    fixture_backed: bool
    created_at: str
    market: str = "KR"
    exchanges: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    currency: str = "KRW"
    timezone: str = "Asia/Seoul"
    candidate_count: int | None = None
    coverage_mode: str = "explicit"
    def to_json(self) -> dict[str, object]:
        return {"schema_version":MULTI_SYMBOL_SCHEMA_VERSION,"universe_id":self.universe_id,"universe_type":self.universe_type.value,"symbols":list(self.symbols),"provenance":self.provenance,"fixture_backed":self.fixture_backed,"created_at":self.created_at,"market":self.market,"exchanges":list(self.exchanges),"currency":self.currency,"timezone":self.timezone,"candidate_count":self.candidate_count,"selected_count":len(self.symbols),"coverage_mode":self.coverage_mode,"exhaustive":self.candidate_count==len(self.symbols) if self.candidate_count is not None else None}


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


_EXCLUSION_CATEGORY_QUALITY_CODES: Mapping[str, str] = {
    "insufficient_lookback": "insufficient_bars",
    "duplicate_bars": "data_quality_failure",
    "invalid_ohlc": "data_quality_failure",
    "symbol_mismatch": "data_quality_failure",
    "negative_volume": "data_quality_failure",
    "timestamp_ordering": "data_quality_failure",
    "abnormal_volume": "data_quality_failure",
    # See _multi_symbol_blocking_findings below: after that filter, a
    # "zero_volume" finding only ever survives into blocking_findings when
    # it is part of a sustained run reaching the dataset's last bar - real
    # evidence the symbol stopped trading, not a generic quality problem.
    "zero_volume": "stale_data",
}

# Patch 8.4 production bug fix, confirmed against REAL KIS-master + Yahoo
# KOSPI/KOSDAQ data (not fixtures, not guessed): DataQualityEngine.validate
# correctly labels an individual zero-volume bar severity="warning" - it is
# a genuine, common KRX market artifact (thin trading, preferred shares,
# holiday-adjacent sessions), not a data-integrity error. But
# krx_real_pipeline._blocking_quality_findings treats ANY finding whose
# code is not in the narrow ALLOWED_RELEASE_WARNING_CODES allowlist as
# blocking regardless of severity - and the raw "zero_volume" code (used
# whenever no registered-anomaly classifier is supplied, which is the case
# for GlobalMarketDataProvider.validate_dataset, the provider market-wide
# research actually uses) is not in that allowlist. The result: a single
# isolated zero-volume day anywhere in a 5-year window silently excluded an
# otherwise perfectly healthy, actively-traded real KOSPI/KOSDAQ stock.
#
# A real production investigation (15 real symbols, live network fetch,
# 2026-08) measured this directly: 12 of 15 symbols had zero-volume ratios
# of 0.6%-6.6% with a longest consecutive run of at most 16 bars, none of
# which reached the dataset's last bar - a normal, scattered artifact.
# Exactly 2 of 15 showed a SUSTAINED run of identical-price, zero-volume
# bars reaching all the way to the most recently requested bar (15 and 473
# consecutive bars respectively) - real evidence the security stopped
# trading (halt/delisting/provider staleness), genuinely distinct from the
# other 12.
#
# This module does NOT touch krx_real_pipeline._blocking_quality_findings
# or DataQualityEngine (both are shared with the single-symbol deep-
# validation pipeline's deliberately conservative, registry-based
# zero-volume policy - Patch 8.1's design, unmodified here). It only
# refines what counts as "blocking" for THIS module's cross-symbol breadth
# evaluation, where reviewing/registering every legitimate zero-volume date
# for the entire live KOSPI+KOSDAQ market is not feasible: an isolated
# zero-volume warning no longer excludes a symbol; a tail-stale run still
# does, now honestly labeled "stale_data" instead of a generic
# "data_quality_failure".
_TAIL_STALE_ZERO_VOLUME_RUN_THRESHOLD = 5


def _tail_stale_zero_volume_dates(dataset: MarketDataset) -> frozenset[str]:
    """Returns the bar dates in a consecutive run of zero-volume bars that
    reaches the dataset's most recently fetched bar, if that run is at
    least ``_TAIL_STALE_ZERO_VOLUME_RUN_THRESHOLD`` bars long - real
    evidence the symbol stopped trading, not an isolated artifact. Returns
    an empty set for every other case (including zero-volume runs
    elsewhere in the middle of the history, which do not indicate the
    symbol is stale AS OF the requested end date)."""
    bars = sorted(dataset.bars, key=lambda bar: bar.timestamp)
    run: list[str] = []
    for bar in reversed(bars):
        if bar.volume != 0:
            break
        run.append(bar.timestamp)
    if len(run) < _TAIL_STALE_ZERO_VOLUME_RUN_THRESHOLD:
        return frozenset()
    return frozenset(run)


_ZERO_VOLUME_FINDING_DATE = re.compile(r"date=(\d{4}-\d{2}-\d{2})")


def _multi_symbol_blocking_findings(quality: DataQualityReport, dataset: MarketDataset) -> tuple[DataQualityFinding, ...]:
    """The cross-symbol breadth-evaluation refinement of
    ``krx_real_pipeline._blocking_quality_findings`` described above: every
    OTHER finding (all severity="error" data-integrity findings, and any
    non-zero_volume warning) is treated exactly as it already was. Only an
    isolated (non-tail-stale-run) "zero_volume" finding is removed from the
    blocking set - it remains visible in the dataset's full quality report
    (``quality_status`` stays "pass_with_warnings"), it simply no longer
    excludes the symbol from strategy research."""
    tail_stale_dates = _tail_stale_zero_volume_dates(dataset)
    blocking: list[DataQualityFinding] = []
    for finding in _blocking_quality_findings(quality):
        if finding.code == "zero_volume":
            match = _ZERO_VOLUME_FINDING_DATE.search(finding.message)
            if match is None or match.group(1) not in tail_stale_dates:
                continue
        blocking.append(finding)
    return tuple(blocking)

# AutonomousMultiSymbolResearchOrchestrator._symbol_evidence attaches this
# sentinel finding code to ANY exception raised while fetching/building a
# symbol's dataset (see multi_symbol.py's `except Exception as exc:` handler) -
# it marks WHERE the failure happened (the acquisition path, before any real
# DataQualityEngine finding was ever produced), it is not itself a data-quality
# finding, and must never be classified as one. The real cause has to be read
# from `blocked_reason` (the actual exception class name and message).
_ACQUISITION_EXCEPTION_FINDING_CODE = "provider_failure"


def _classify_exclusion_reason(item: "SymbolResearchEvidence") -> str:
    """Classifies why a symbol was excluded from a multi-symbol research run.

    Acquisition-side failures (provider fetch failures, timeouts, symbol
    resolution failures - anything that happened before a dataset was ever
    quality-validated) are classified from ``blocked_reason``, the actual
    exception class/message the pipeline recorded, and are always checked
    ahead of - and kept separate from - real DataQualityEngine findings in
    ``blocking_findings``. A symbol that failed to fetch is never reported as
    a data-quality problem. Unclassifiable failures fall back to "other"
    rather than guessing.
    """
    if item.eligible:
        return "eligible"
    quality_codes = {
        str(finding.get("code", ""))
        for finding in item.blocking_findings
        if str(finding.get("code", "")) != _ACQUISITION_EXCEPTION_FINDING_CODE
    }
    if quality_codes:
        for code in quality_codes:
            if code in _EXCLUSION_CATEGORY_QUALITY_CODES:
                return _EXCLUSION_CATEGORY_QUALITY_CODES[code]
        return "data_quality_failure"
    return _classify_acquisition_failure(item.blocked_reason)


def _classify_acquisition_failure(blocked_reason: str | None) -> str:
    """Classifies a symbol that failed before reaching data-quality
    validation, from the exception class name/message the pipeline actually
    recorded. Only names a specific cause the message evidence supports;
    falls back to "other" rather than inventing one."""
    reason = (blocked_reason or "").casefold()
    if not reason:
        return "other"
    if "timeout" in reason:
        return "timeout"
    if "kis" in reason and ("mismatch" in reason or "master" in reason):
        return "kis_master_mismatch"
    if "unsupported" in reason:
        return "unsupported_security"
    if any(token in reason for token in ("symbol not found", "symbol resolution", "unresolved symbol", "unknown symbol", "no symbols")):
        return "symbol_resolution_failure"
    if any(
        token in reason
        for token in (
            "realmarketdataunavailable",
            "connectionerror",
            "urlerror",
            "httperror",
            "no bars",
            "no usable bars",
            "fetch",
            "network",
            "connection",
        )
    ):
        return "provider_fetch_failure"
    return "other"


def _exclusion_diagnostics(evidence: tuple["SymbolResearchEvidence", ...]) -> dict[str, object]:
    excluded = tuple(item for item in evidence if not item.eligible)
    by_category: dict[str, int] = {}
    for item in excluded:
        category = _classify_exclusion_reason(item)
        by_category[category] = by_category.get(category, 0) + 1
    provider_categories = {"provider_fetch_failure", "timeout", "kis_master_mismatch", "symbol_resolution_failure"}
    provider_related = sum(count for category, count in by_category.items() if category in provider_categories)
    return {
        "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
        "total_excluded": len(excluded),
        "by_category": by_category,
        "provider_related_excluded": provider_related,
        "excluded_symbols": [item.symbol for item in excluded],
    }


_RESOLUTION_STAGE_FAILURE_CATEGORIES = frozenset({"symbol_resolution_failure", "kis_master_mismatch"})


def _acquisition_funnel(evidence: tuple["SymbolResearchEvidence", ...]) -> dict[str, object]:
    """Structured acquisition-funnel counts:
    selected -> symbol_resolved -> provider_fetch_started ->
    provider_fetch_succeeded -> ohlcv_received -> quality_checked ->
    quality_passed -> research_eligible -> strategy_tested.

    Every count here is aggregated ONLY from the real per-symbol
    ``SymbolResearchEvidence`` this run actually produced - never
    fabricated or estimated. Some adjacent stages are currently equal by
    construction rather than independently observed, and this is reported
    honestly rather than invented:
    - the pipeline fetches one symbol per request and raises before ever
      returning a dataset with zero bars (see
      ``YahooKRXHistoricalDataProvider``/``GlobalMarketDataProvider.
      fetch_bars``), so "fetch succeeded" and "OHLCV received" are the
      same observable event today (``rows > 0``);
    - ``DataQualityEngine`` runs unconditionally immediately after every
      successful fetch, so "quality checked" is also that same count;
    - nothing currently distinguishes "quality passed" from "research
      eligible" - they are the same boolean (``eligible``) in the current
      design;
    - every eligible symbol is backtested, so "strategy tested" equals
      "research eligible" unless a symbol failed AFTER eligibility was
      determined (not currently possible, but computed independently
      below rather than assumed equal, so a future change that makes this
      possible is reflected honestly).
    """
    selected = len(evidence)
    resolution_failed = sum(
        1 for item in evidence if not item.eligible and _classify_exclusion_reason(item) in _RESOLUTION_STAGE_FAILURE_CATEGORIES
    )
    fetched = sum(1 for item in evidence if item.rows > 0)
    quality_passed = sum(1 for item in evidence if item.eligible)
    strategy_tested = sum(1 for item in evidence if item.eligible and item.backtest_result is not None)
    return {
        "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
        "selected": selected,
        "symbol_resolved": max(0, selected - resolution_failed),
        "provider_fetch_started": selected,
        "provider_fetch_succeeded": fetched,
        "ohlcv_received": fetched,
        "quality_checked": fetched,
        "quality_passed": quality_passed,
        "research_eligible": quality_passed,
        "strategy_tested": strategy_tested,
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
    adaptive_sampling: dict[str, object] | None = None
    exclusion_diagnostics: dict[str, object] | None = None
    acquisition_funnel: dict[str, object] | None = None

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
            "adaptive_sampling": dict(self.adaptive_sampling or {}),
            "exclusion_diagnostics": dict(self.exclusion_diagnostics or _exclusion_diagnostics(self.evidence)),
            "acquisition_funnel": dict(self.acquisition_funnel or _acquisition_funnel(self.evidence)),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
            "approval_required_before_config_change": True,
        }


class KRXResearchUniverseResolver:
    def resolve(self, symbols: tuple[str, ...] | None = None, *, universe_type: str = "explicit", universe_result: KRXUniverseResult | None = None, created_at: str | None = None, market_scope: MarketScope | None = None, candidate_count: int | None = None, provenance: str | None = None, coverage_mode: str | None = None) -> KRXResearchUniverse:
        at=created_at or utc_now()
        if symbols:
            normalized=_normalize_symbols(symbols); kind=UniverseType.CURATED if universe_type=="curated" else UniverseType.EXPLICIT; scope=market_scope; market=scope.market if scope else "KR"; exchanges=scope.exchanges if scope else ("KOSPI","KOSDAQ"); currency=scope.primary_currency if scope else "KRW"; timezone=scope.primary_timezone if scope else "Asia/Seoul"; prov=provenance or ("market_provider_snapshot" if kind is UniverseType.CURATED else "explicit_user_provided"); uid=f"universe:{market.lower()}:{kind.value}:{_sha({'symbols':normalized,'market':market})[:12]}"
            return KRXResearchUniverse(uid,kind,normalized,prov,False,at,market,exchanges,currency,timezone,candidate_count,coverage_mode or ("bounded_sample" if kind is UniverseType.CURATED else "explicit"))
        if universe_result is not None:
            exchanges=("KOSPI","KOSDAQ") if universe_result.request.market=="ALL" else (universe_result.request.market,)
            return KRXResearchUniverse(universe_result.universe_id,UniverseType.CURATED,universe_result.symbols,f"dynamic_{universe_result.request.ranking_metric}",universe_result.fixture_backed,at,"KR",exchanges,"KRW","Asia/Seoul",int(universe_result.data_quality_summary.get("candidate_count",universe_result.selected_size)),"ranked_trading_value")
        if universe_type=="curated": return KRXResearchUniverse("universe:curated:krx-largecap-v1",UniverseType.CURATED,DEFAULT_CURATED_SYMBOLS,"curated_static_research_universe_v1",False,at)
        return KRXResearchUniverse(f"universe:explicit:{_sha({'symbols':DEFAULT_CURATED_SYMBOLS})[:12]}",UniverseType.EXPLICIT,DEFAULT_CURATED_SYMBOLS,"explicit_default_release_universe",False,at)


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
    def __init__(self, connection: sqlite3.Connection | None = None, provider: MarketDataProvider | KRXHistoricalDataProvider | None = None, runner: MultiSymbolBacktestRunner | None = None) -> None:
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
        universe_result: KRXUniverseResult | None = None,
        start_date: str = "2021-07-25",
        end_date: str = "2026-07-24",
        run_id: str | None = None,
        generated_at: str | None = None,
        candidate_spec: Mapping[str, object] | None = None,
        avoid_symbols: tuple[str, ...] = (),
    ) -> MultiSymbolResearchRun:
        at=generated_at or utc_now()
        rid=run_id or f"multi-symbol-research:{uuid4().hex}"
        market_scope=resolve_market_scope(request_text,require_universe=True); selection=None; candidate_pool=()

        # Overseas and multi-market research must use the market-agnostic
        # provider even when symbols were explicitly supplied.
        #
        # Explicit symbols still retain precedence over universe sampling,
        # but the KIS master is loaded first so the provider learns the
        # authoritative exchange for symbols such as AAPL/IBM/BRK.B.
        if (
            market_scope is not None
            and market_scope.market in {"US", "JP", "HK", "CN", "MULTI", "GLOBAL"}
            and not getattr(self._provider, "market_agnostic", False)
        ):
            provider = GlobalMarketDataProvider.from_env(os.environ)

            try:
                provider.fetch_universe(
                    market_scope.selector
                )
            except Exception as exc:
                if isinstance(exc, RealMarketDataUnavailable):
                    raise
                raise RealMarketDataUnavailable(
                    "real_data_unavailable: global market "
                    f"universe unavailable: {exc.__class__.__name__}"
                ) from exc

            self._provider = provider

        if not symbols and universe_result is None and market_scope is not None:
            provider=self._provider
            if not getattr(provider,"market_agnostic",False): provider=GlobalMarketDataProvider.from_env(os.environ)
            try:
                candidates=provider.fetch_universe(market_scope.selector)
                candidate_pool=tuple(candidates)
            except Exception as exc:
                if isinstance(exc,RealMarketDataUnavailable): raise
                raise RealMarketDataUnavailable(f"real_data_unavailable: global market universe unavailable: {exc.__class__.__name__}") from exc
            selection=select_bounded_universe(candidates,market_scope,requested_size=research_sample_size(os.environ),seed=f"{end_date}|{request_text}",source=getattr(provider,"source","unknown"),avoid_symbols=frozenset(str(item).upper() for item in avoid_symbols)); symbols=selection.symbols; universe_type="curated"; self._provider=provider
        universe=KRXResearchUniverseResolver().resolve(symbols,universe_type=universe_type,universe_result=universe_result,created_at=at,market_scope=market_scope,candidate_count=selection.candidate_count if selection else None,provenance=selection.source if selection else None,coverage_mode=selection.coverage_mode if selection else None)
        if not universe.symbols:
            raise RealMarketDataUnavailable("real_data_unavailable: universe has no symbols")
        strategy = (
            _strategy_from_candidate_spec(candidate_spec, symbol=universe.symbols[0], created_at=at)
            if candidate_spec is not None
            else UserStrategyParser().parse(request_text or DEFAULT_REQUEST_TEXT, symbol=universe.symbols[0], created_at=at)
        )
        assumptions = default_execution_assumptions()
        evidence: list[SymbolResearchEvidence] = []
        self._dataset_cache = {}
        provider_name = getattr(self._provider, "source", "unknown")
        for symbol in universe.symbols:
            item = self._symbol_evidence(rid, request_text, symbol, start_date, end_date, strategy, assumptions, at)
            evidence.append(item)
        summary = aggregate_symbol_evidence(tuple(evidence))
        adaptive_sampling = {
            "sampling_rounds": 1,
            "attempted_symbols": len(evidence),
            "eligible_symbols": summary.eligible_symbols,
            "blocked_symbols": summary.blocked_symbols,
            "exchange_coverage": {},
            "stop_reason": "initial_sample_sufficient" if summary.sample_confidence != "low" else "initial_sample_insufficient",
            "evidence_sufficient": summary.sample_confidence != "low",
            "research_budget_used": len(evidence),
            "research_budget_limit": len(evidence),
        }
        if selection is not None and market_scope is not None and candidate_pool:
            budget = adaptive_budget(os.environ, len(evidence), len(candidate_pool))
            rounds = 1
            if summary.sample_confidence == "low" and len(evidence) < budget and selection.coverage_mode != "exhaustive":
                batches = adaptive_batches(
                    candidate_pool,
                    market_scope.exchanges,
                    (*(item.symbol for item in evidence), *avoid_symbols),
                    budget,
                    max(1, research_sample_size(os.environ)),
                    f"{end_date}|{request_text}|adaptive-v7",
                )
                for batch in batches:
                    if not batch:
                        continue
                    rounds += 1
                    for symbol in batch:
                        if any(item.symbol == symbol.upper() for item in evidence):
                            continue
                        evidence.append(self._symbol_evidence(
                            rid, request_text, symbol, start_date, end_date,
                            strategy, assumptions, at,
                        ))
                    summary = aggregate_symbol_evidence(tuple(evidence))
                    if summary.sample_confidence != "low":
                        break
            refs = {item.symbol.upper(): item for item in candidate_pool}
            coverage = {}
            for item in evidence:
                ref = refs.get(item.symbol.upper())
                if ref is not None:
                    ex = ref.exchange.upper()
                    coverage[ex] = coverage.get(ex, 0) + 1
            sufficient = summary.sample_confidence != "low"
            adaptive_sampling = {
                "sampling_rounds": rounds,
                "attempted_symbols": len(evidence),
                "eligible_symbols": summary.eligible_symbols,
                "blocked_symbols": summary.blocked_symbols,
                "exchange_coverage": coverage,
                "stop_reason": "evidence_sufficient" if sufficient else (
                    "research_budget_exhausted" if len(evidence) >= budget else "candidate_pool_exhausted"
                ),
                "evidence_sufficient": sufficient,
                "research_budget_used": len(evidence),
                "research_budget_limit": budget,
            }
            universe = replace(
                universe,
                symbols=tuple(item.symbol for item in evidence),
                candidate_count=len(candidate_pool),
                coverage_mode="adaptive_bounded_cross_exchange_sample" if rounds > 1 else universe.coverage_mode,
            )
        candidate_results = self._candidate_evidence(rid, strategy, assumptions, tuple(evidence), at)
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
        report = render_multi_symbol_report(request, tuple(evidence), summary, generalization, recommendation, adaptive_sampling=adaptive_sampling)
        exclusion_diagnostics = _exclusion_diagnostics(tuple(evidence))
        acquisition_funnel = _acquisition_funnel(tuple(evidence))
        run = MultiSymbolResearchRun(rid, request, strategy, assumptions, tuple(evidence), candidate_results, summary, generalization, recommendation, report, at, adaptive_sampling=adaptive_sampling, exclusion_diagnostics=exclusion_diagnostics, acquisition_funnel=acquisition_funnel)
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
            if getattr(self._provider,"market_agnostic",False):
                dataset=self._provider.fetch_bars(symbol,start_date=start_date,end_date=end_date); validator=getattr(self._provider,"validate_dataset",None); quality=validator(dataset) if callable(validator) else DataQualityEngine().validate(dataset,min_bars=60)
                if self._connection is not None: SQLiteDatasetRegistry(self._connection).put_dataset(dataset,quality)
            else:
                dataset,quality,_inserted=KRXDatasetBuilder(self._connection,self._provider).build(symbol,start_date=start_date,end_date=end_date)
            self._dataset_cache[symbol.upper()] = dataset
            blocking = _multi_symbol_blocking_findings(quality, dataset)
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
    best = max(
        eligible_rows,
        key=lambda row: (
            float(row["median_return"] or 0.0),
            -float(row["median_mdd"] or 1.0),
            int(row["aggregate_trade_count"] or 0),
        ),
    )
    original_row = rows[0]
    if best["candidate_id"] == "original":
        return CandidateGeneralization(
            CandidateGeneralizationDecision.ORIGINAL_PREFERRED,
            "original",
            tuple(rows),
            "original has the strongest generalized evidence by median return, drawdown, and trade sample",
        )
    return_improved = float(best["median_return"] or 0.0) > float(original_row["median_return"] or 0.0)
    breadth_preserved = int(best["symbols_with_trades"] or 0) >= int(original_row["symbols_with_trades"] or 0)
    trade_sample_preserved = int(best["aggregate_trade_count"] or 0) >= int(original_row["aggregate_trade_count"] or 0)
    mdd_not_worse = float(best["median_mdd"] or 1.0) <= float(original_row["median_mdd"] or 1.0)
    if return_improved and breadth_preserved and trade_sample_preserved and mdd_not_worse:
        return CandidateGeneralization(
            CandidateGeneralizationDecision.CANDIDATE_PREFERRED,
            str(best["candidate_id"]),
            tuple(rows),
            "tested candidate improves median return without reducing symbol breadth, trade sample, or median MDD",
        )
    blockers: list[str] = []
    if return_improved:
        blockers.append("median return improved")
    if not breadth_preserved:
        blockers.append("symbols with trades decreased")
    if not trade_sample_preserved:
        blockers.append("aggregate trade sample decreased")
    if not mdd_not_worse:
        blockers.append("median MDD worsened")
    reason = "candidate evidence is mixed across symbols"
    if blockers:
        reason = "candidate is not preferred because " + ", ".join(blockers)
    return CandidateGeneralization(CandidateGeneralizationDecision.NO_CLEAR_WINNER, None, tuple(rows), reason)


def render_multi_symbol_report(request: MultiSymbolResearchRequest, evidence: tuple[SymbolResearchEvidence, ...], summary: UniverseResearchSummary, generalization: CandidateGeneralization, recommendation: str, *, adaptive_sampling: dict[str, object] | None = None) -> str:
    def pct(value):
        if value is None: return "계산 불가"
        try: return f"{float(value)*100:+.1f}%"
        except (TypeError,ValueError): return "계산 불가"
    confidence={"low":"낮음","medium":"보통","high":"높음"}.get(summary.sample_confidence,summary.sample_confidence)
    conclusions={
        CandidateGeneralizationDecision.NEEDS_MORE_EVIDENCE:"아직 결론을 내리기에는 증거가 부족합니다.",
        CandidateGeneralizationDecision.CANDIDATE_PREFERRED:"검증된 개선 후보가 기존 전략보다 나은 가능성을 보였습니다.",
        CandidateGeneralizationDecision.ORIGINAL_PREFERRED:"현재 증거에서는 기존 전략이 가장 안정적입니다.",
        CandidateGeneralizationDecision.NO_CLEAR_WINNER:"후보 간 우열이 뚜렷하지 않습니다.",
    }
    conclusion=conclusions[generalization.decision]
    sampling=dict(adaptive_sampling or {})
    lines=[
        "[다중종목 실제 연구]","[연구 결과]","","[결론]",conclusion,"",
        "[이번 batch]",
        f"- market={request.universe.market}",
        f"- 시장: {request.universe.market}",
        f"- 거래소: {', '.join(request.universe.exchanges)}",
        f"- 실제 데이터: {request.provider} / fixture_backed={str(request.fixture_backed).lower()}",
        f"- 기간: {request.period_start} ~ {request.period_end}",
        f"- 연구 시도: {len(evidence)}종목",
        f"- 정상 검증: {summary.eligible_symbols}종목",
        f"- 데이터 문제로 제외: {summary.blocked_symbols}종목",
        f"- 총 거래 표본: {summary.aggregate_trade_count}회",
        f"- 연구 신뢰도: {confidence}",
    ]
    funnel = _acquisition_funnel(evidence)
    lines.append(
        "- acquisition funnel: selected={selected} resolved={symbol_resolved} fetched={provider_fetch_succeeded} "
        "quality_passed={quality_passed} eligible={research_eligible} tested={strategy_tested}".format(**funnel)
    )
    exclusion = _exclusion_diagnostics(evidence)
    by_category = exclusion.get("by_category") or {}
    if isinstance(by_category, dict) and by_category:
        lines.extend(["", "[제외 사유]"])
        for category, count in sorted(by_category.items()):
            lines.append(f"- {category}: {count}종목")
        if exclusion.get("provider_related_excluded") and exclusion["provider_related_excluded"] == exclusion.get("total_excluded"):
            lines.append("- 제외 사유가 모두 데이터 제공자/조회 문제이며, 전략 자체의 실패로 판단하지 않습니다.")
    if sampling:
        lines.extend(["","[batch 표본 확장]",
            f"- batch research rounds: {sampling.get('sampling_rounds',1)}회",
            f"- batch budget: {sampling.get('research_budget_used',len(evidence))}/{sampling.get('research_budget_limit',len(evidence))}종목",
            f"- 종료 이유: {sampling.get('stop_reason','unknown')}"])
        coverage=sampling.get("exchange_coverage")
        if isinstance(coverage,dict) and coverage:
            lines.append("- 거래소 표본: "+", ".join(f"{k} {v}" for k,v in sorted(coverage.items())))
    lines.extend(live_report_lines(production_feedback(request.universe.market)))
    original=generalization.rows[0] if generalization.rows else {}
    lines.extend(["","[기존 전략]",
        f"- 중앙 수익률: {pct(original.get('median_return'))}",
        f"- 중앙 MDD: {pct(original.get('median_mdd'))}",
        f"- 총 거래: {original.get('aggregate_trade_count',summary.aggregate_trade_count)}회",
        f"- 수익 종목 비율: {pct(original.get('profitable_symbol_ratio'))}"])
    candidates=[row for row in generalization.rows if row.get("candidate_id")!="original"]
    if candidates:
        lines.extend(["","[개선 후보]"])
        for i,row in enumerate(candidates):
            label=chr(65+i) if i<26 else str(i+1)
            star=" ⭐" if row.get("candidate_id")==generalization.winner_id else ""
            lines.append(f"- 후보 {label}{star}: 중앙 수익률 {pct(row.get('median_return'))}, MDD {pct(row.get('median_mdd'))}, 거래 {row.get('aggregate_trade_count',0)}회")
    lines.extend(["","[가온의 판단]",f"- {conclusion}", f"- 판단 근거: {generalization.reason}"])
    lines.extend(["","[누적 Research Mission]","- 누적 유효 종목/거래 수는 상단 전략 후보 블록의 canonical candidate state를 기준으로 판단합니다."])
    if summary.sample_confidence=="low":
        lines.append("- 현재 표본만으로 일반화하지 않고 추가 검증이 필요합니다.")
    elif generalization.decision is CandidateGeneralizationDecision.CANDIDATE_PREFERRED:
        lines.append("- 개선 후보는 자동 승격하지 않고 추가 OOS/강건성 검증 대상으로 둡니다.")
    else:
        lines.append("- 서로 다른 종목·기간에서도 같은 결과가 반복되는지 확인해야 합니다.")
    lines.extend(["","[다음 연구]"])
    if sampling.get("stop_reason")=="candidate_pool_exhausted":
        lines.append("- 중복되지 않는 후보 종목 풀이 소진되었습니다. 같은 EXPAND_SAMPLE을 반복하지 않고 누적 증거로 후보 viability를 판정합니다.")
    elif sampling.get("stop_reason")=="research_budget_exhausted":
        lines.append("- 설정된 연구 budget을 모두 사용했습니다. 다음 표본/기간으로 증거를 확장합니다.")
    elif summary.sample_confidence=="low":
        lines.append("- 중복되지 않는 대표 종목을 추가해 표본 신뢰도를 높입니다.")
    else:
        lines.append("- 우수 후보를 OOS·walk-forward·비용 스트레스 검증으로 넘기는 것이 적절합니다.")
    lines.extend(["","[Safety]","- 자동 주문 없음","- Champion 자동 승격 없음","- 승인 없는 config 변경 없음"])
    return "\n".join(lines)


def multi_symbol_research_payload(connection: sqlite3.Connection, request_text: str, *, symbols: tuple[str, ...] | None = None, universe_type: str = "explicit", start_date: str = "2021-07-25", end_date: str = "2026-07-24", candidate_spec: Mapping[str, object] | None = None, avoid_symbols: tuple[str, ...] = ()) -> dict[str, object]:
    run = AutonomousMultiSymbolResearchOrchestrator(connection, build_market_data_provider_from_env(os.environ)).run(request_text, symbols=symbols, universe_type=universe_type, start_date=start_date, end_date=end_date, candidate_spec=candidate_spec, avoid_symbols=avoid_symbols)
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


class _DataAcquisitionDiagnosticsReleaseCheckProvider:
    """Deterministic, network-free provider for
    ``production_kr_multi_symbol_data_acquisition_release_check``.

    Wraps the existing ``_ReleaseCheckProvider`` and injects the exact
    zero-volume patterns a real production investigation confirmed
    (isolated scattered zero-volume bars for most symbols, one sustained
    tail-stale run, one outright provider fetch failure) - deliberately
    NOT a live network call, so this release check's result never depends
    on real-time market/provider availability.
    """

    source = "real:synthetic-release-check"

    def __init__(self) -> None:
        self._delegate = _ReleaseCheckProvider()

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        from gaon.research.real_research import MarketBar

        upper = symbol.upper()
        if upper == "999999":
            raise RealMarketDataUnavailable(f"real_data_unavailable: no bars returned for {symbol}")
        dataset = self._delegate.fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)
        bars = list(dataset.bars)
        if upper == "888888":
            zero_indices = range(max(0, len(bars) - 10), len(bars))  # tail-stale run
        else:
            zero_indices = (index for index in (5, 40, 90) if index < len(bars))  # isolated
        for index in zero_indices:
            bar = bars[index]
            bars[index] = MarketBar(bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, 0, 0)
        return MarketDataset(dataset.dataset_id, dataset.symbols, tuple(bars), dataset.metadata)


def production_kr_multi_symbol_data_acquisition_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    """Deterministic, network-free release check for Patch 8.4.

    Exercises the real production defect this patch fixes: a market-wide
    cross-symbol research cycle against real KOSPI/KOSDAQ data excluded
    13-15 of 15 symbols as a generic "data_quality_failure" - confirmed
    (via a live network investigation during this patch, not guessed) to
    be almost entirely isolated, non-blocking zero-volume warnings
    (a normal KRX market artifact) being wrongly treated as blocking.
    Deliberately uses a synthetic, deterministic provider (never live
    network) so this release check's result never depends on real-time
    market/provider availability.
    """
    from gaon.knowledge.research_mission import (
        MissionUniverseScope,
        extract_or_update_mission,
        is_provider_acquisition_blocker,
        update_candidate as mission_update_candidate,
    )
    from gaon.knowledge.strategy_candidate import new_candidate, record_breadth_progress

    symbols = ("111111", "222222", "333333", "444444", "555555", "666666", "777777", "888888", "999999")
    provider = _DataAcquisitionDiagnosticsReleaseCheckProvider()
    run = AutonomousMultiSymbolResearchOrchestrator(connection, provider, _ReleaseCheckBacktestRunner()).run(
        DEFAULT_REQUEST_TEXT,
        run_id=f"gaon-production-kr-multi-symbol-data-acquisition-release-check:{uuid4().hex}",
        symbols=symbols,
        start_date="2021-07-25",
        end_date="2026-07-24",
        generated_at=utc_now(),
    )
    payload = run.to_json()
    funnel = dict(payload["acquisition_funnel"])
    diagnostics = dict(payload["exclusion_diagnostics"])
    by_category = dict(diagnostics.get("by_category") or {})

    acquisition_funnel_structured = (
        all(
            stage in funnel
            for stage in (
                "selected", "symbol_resolved", "provider_fetch_started", "provider_fetch_succeeded",
                "ohlcv_received", "quality_checked", "quality_passed", "research_eligible", "strategy_tested",
            )
        )
        and funnel["selected"] == len(symbols)
    )
    exclusion_reason_evidence_backed = (
        diagnostics["total_excluded"] == 2
        and by_category.get("provider_fetch_failure") == 1
        and by_category.get("stale_data") == 1
    )
    provider_failure_not_data_quality = by_category.get("data_quality_failure", 0) == 0
    research_eligible_only_tested = funnel["strategy_tested"] == funnel["research_eligible"] and funnel["research_eligible"] == 7

    # Direct classifier checks (pure functions, no orchestrator run needed) -
    # confirm timeout and insufficient-history-shaped acquisition reasons are
    # never conflated with data-quality or provider-failure categories.
    timeout_not_data_quality = _classify_acquisition_failure("TimeoutError: provider request timed out") == "timeout"
    insufficient_history_not_provider_failure = (
        _classify_exclusion_reason(
            SymbolResearchEvidence(
                "evidence:recent-listing", "555555", False, "blocking_data_quality", None, None, "fail",
                "real:kis-master+yahoo-chart", "unknown", False, 0, (), (), (),
                ({"code": "insufficient_lookback", "severity": "error", "message": "too few bars"},),
                {"trade_count": 0}, None, (),
            )
        )
        == "insufficient_bars"
    )

    # Bounded retry/replacement: avoiding every candidate never blocks
    # sampling (falls back to the full pool, still capped at requested_size).
    from gaon.research.global_market import MarketScope

    bounded_scope = MarketScope("KR", ("KOSPI",), ("KRW",), ("Asia/Seoul",), True, "release-check")
    bounded_candidates = tuple(MarketSymbol(symbol, symbol, "KR", "KOSPI") for symbol in symbols)
    bounded_selection = select_bounded_universe(
        bounded_candidates, bounded_scope, requested_size=3, seed="release-check", source="test",
        avoid_symbols=frozenset(symbols),
    )
    bounded_retry_cap_preserved = len(bounded_selection.symbols) == 3

    # Mission scope / candidate fingerprint preservation: this patch must
    # never touch ResearchMission or StrategyCandidate identity - simulate
    # exactly what the real breadth cycle does with this run's evidence and
    # confirm both are unchanged.
    now = utc_now()
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=now)
    candidate = new_candidate("breakout_standard", sequence=1, now=now)
    fingerprint_before = candidate.strategy_fingerprint
    valid_items = tuple(item for item in run.evidence if item.eligible)
    excluded_items = tuple(item for item in run.evidence if not item.eligible)
    provider_blocked = is_provider_acquisition_blocker(diagnostics)
    progressed = record_breadth_progress(
        candidate,
        attempted=len(run.evidence),
        valid=len(valid_items),
        trade_count=run.summary.aggregate_trade_count,
        evidence_symbols=tuple(item.symbol for item in valid_items),
        excluded_symbols=tuple(item.symbol for item in excluded_items),
        provider_blocked=provider_blocked,
        now=now,
    )
    mission = mission_update_candidate(mission, progressed, now=now)
    mission_scope_unchanged = mission.universe_scope is MissionUniverseScope.MARKET_WIDE and mission.market == "KR"
    candidate_fingerprint_unchanged = progressed.strategy_fingerprint == fingerprint_before

    checks = {
        "acquisition_funnel_structured": acquisition_funnel_structured,
        "exclusion_reason_evidence_backed": exclusion_reason_evidence_backed,
        "provider_failure_not_misclassified_as_data_quality_failure": provider_failure_not_data_quality,
        "timeout_not_misclassified_as_data_quality_failure": timeout_not_data_quality,
        "insufficient_history_not_misclassified_as_provider_failure": insufficient_history_not_provider_failure,
        "research_eligible_only_passed_to_strategy_validation": research_eligible_only_tested,
        "bounded_retry_cap_preserved": bounded_retry_cap_preserved,
        "mission_scope_unchanged": mission_scope_unchanged,
        "candidate_fingerprint_unchanged": candidate_fingerprint_unchanged,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RealMarketDataUnavailable(f"kr multi-symbol data acquisition release check failed: {failed}")

    return {
        "schema_version": MULTI_SYMBOL_SCHEMA_VERSION,
        **checks,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def telegram_multi_symbol_research_release_check(connection: sqlite3.Connection, *, tool_executor_factory=None) -> dict[str, object]:
    from gaon.runtime.config import GaonRuntimeConfig
    from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
    from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
    from gaon.runtime.routing_debug import telegram_routing_debug_payload

    config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
    executor = tool_executor_factory(connection) if tool_executor_factory else SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection))
    from gaon.runtime.llm_conversation import SQLiteConversationRepository, SQLiteConversationToolResultRepository

    brain = LLMConversationBrain(config, SQLiteConversationRepository(connection), tool_executor=executor, tool_result_repository=SQLiteConversationToolResultRepository(connection))
    run_id = f"telegram-multi-symbol-research-release-check:{uuid4().hex}"
    request_text = PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT
    routing = telegram_routing_debug_payload(request_text)
    multi_symbol_evidence = dict(routing.get("multi_symbol_evidence", {}))
    if not multi_symbol_evidence.get("execution_intent") or multi_symbol_evidence.get("history_intent") or multi_symbol_evidence.get("status_intent"):
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol execution intent collided with status/history intent")
    response = brain.respond(LLMConversationRequest(run_id, "release-check", "telegram", request_text, utc_now(), f"{run_id}:message"))
    if response.route != "tool_read_only_authoritative" or "multi_symbol_research" not in response.tool_calls:
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol route was not authoritative")
    if "자동 주문 없음" not in response.text:
        raise RealMarketDataUnavailable("real_data_unavailable: deterministic safety report missing")
    audit_rows = connection.execute("SELECT request_json FROM llm_tool_audit WHERE tool_name = 'multi_symbol_research' ORDER BY created_at, audit_id").fetchall()
    if not audit_rows:
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol audit missing")
    request_payload = json.loads(str(audit_rows[-1][0]))
    arguments = dict(request_payload.get("arguments", {}))
    symbols = tuple(arguments.get("symbols", ()))
    if symbols != DEFAULT_CURATED_SYMBOLS:
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol symbol extraction failed")
    if arguments.get("start_date") != "2021-07-25" or arguments.get("end_date") != "2026-07-24":
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol period extraction failed")
    persisted = connection.execute("SELECT COUNT(*) FROM multi_symbol_research_runs WHERE run_id LIKE 'multi-symbol-research:%'").fetchone()[0]
    if int(persisted) < 1:
        raise RealMarketDataUnavailable("real_data_unavailable: Telegram multi-symbol persistence missing")
    return {
        "schema_version": 36,
        "run_id": run_id,
        "route": response.route,
        "tool_calls": list(response.tool_calls),
        "provider_calls": 0,
        "audit_count": len(audit_rows),
        "symbols": list(symbols),
        "start_date": arguments.get("start_date"),
        "end_date": arguments.get("end_date"),
        "persisted_runs": int(persisted),
        "generic_fallback": False,
        "production_language": True,
        "execution_intent": bool(multi_symbol_evidence.get("execution_intent")),
        "history_intent": bool(multi_symbol_evidence.get("history_intent")),
        "status_intent": bool(multi_symbol_evidence.get("status_intent")),
    }


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


def _requested_krx_market_scope(text: str) -> str | None:
    scope=resolve_market_scope(text,require_universe=True)
    if scope is None or scope.market!="KR": return None
    if set(scope.exchanges)=={"KOSPI","KOSDAQ"}: return "ALL"
    return scope.exchanges[0] if len(scope.exchanges)==1 else "ALL"


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

