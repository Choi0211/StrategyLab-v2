"""AI Quant Researcher foundation for Sprint 71-80.

The workflow is advisory and fixture-backed by default. It never places orders,
promotes Champions, or changes user-approved strategy state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import json
import re
import sqlite3

from gaon.adapters.backtest import BacktestMetrics
from gaon.runtime.external_research import FreshnessStatus, SourceProvenance, TrustClassification


ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
THEME_KEYWORDS = {
    "AI": ("ai", "인공지능", "npu"),
    "semiconductor": ("semiconductor", "반도체", "hbm", "chip"),
    "robot": ("robot", "로봇", "automation"),
    "defense": ("defense", "방산", "missile"),
    "nuclear": ("nuclear", "원전", "smr"),
}


class ThemeStrength(str, Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    WEAK = "weak"


class ResearchDecision(str, Enum):
    RECOMMEND = "recommend"
    REJECT = "reject"
    NEEDS_MORE_VALIDATION = "needs_more_validation"


@dataclass(frozen=True)
class KRXMarketBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    trading_value: int
    market_cap: int
    foreign_net_buy: int
    institution_net_buy: int
    pension_net_buy: int
    program_net_buy: int
    short_sale_value: int
    source: SourceProvenance

    def to_json(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "ohlc": {"open": self.open, "high": self.high, "low": self.low, "close": self.close},
            "volume": self.volume,
            "trading_value": self.trading_value,
            "market_cap": self.market_cap,
            "foreign_net_buy": self.foreign_net_buy,
            "institution_net_buy": self.institution_net_buy,
            "pension_net_buy": self.pension_net_buy,
            "program_net_buy": self.program_net_buy,
            "short_sale_value": self.short_sale_value,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class NewsItem:
    title: str
    body: str
    symbol: str
    theme: str
    source: SourceProvenance


@dataclass(frozen=True)
class NewsAnalysis:
    symbol: str
    theme: str
    label: str
    score: int
    citations: tuple[str, ...]


@dataclass(frozen=True)
class ThemeAnalysis:
    theme: str
    strength: ThemeStrength
    leader_symbols: tuple[str, ...]
    follower_symbols: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class FlowAnalysis:
    symbol: str
    foreign_5d: int
    foreign_20d: int
    institution_5d: int
    institution_20d: int
    program_5d: int
    program_20d: int
    short_sale_5d: int
    trend: str


@dataclass(frozen=True)
class CandidateStrategy:
    strategy_id: str
    components: tuple[str, ...]
    parameters: dict[str, float | int | str | bool]
    hypothesis: str


@dataclass(frozen=True)
class ResearchBacktest:
    strategy_id: str
    horizon: str
    metrics: BacktestMetrics
    cost_model: dict[str, float]


@dataclass(frozen=True)
class StrategyComparison:
    strategy_id: str
    decision: ResearchDecision
    sharpe: float
    mdd: float
    win_rate: float
    profit_factor: float
    expectancy: float
    champion_delta: float
    automatic_promotion: bool = False


@dataclass(frozen=True)
class AIResearchReport:
    report_id: str
    generated_at: str
    market_sources: tuple[str, ...]
    news: tuple[NewsAnalysis, ...]
    themes: tuple[ThemeAnalysis, ...]
    flows: tuple[FlowAnalysis, ...]
    candidates: tuple[CandidateStrategy, ...]
    backtests: tuple[ResearchBacktest, ...]
    comparisons: tuple[StrategyComparison, ...]
    improved_candidates: tuple[CandidateStrategy, ...]
    evolution_winners: tuple[CandidateStrategy, ...]
    summary: str
    limitations: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "market_sources": list(self.market_sources),
            "news": [item.__dict__ for item in self.news],
            "themes": [
                {"theme": item.theme, "strength": item.strength.value, "leader_symbols": list(item.leader_symbols), "follower_symbols": list(item.follower_symbols), "score": item.score}
                for item in self.themes
            ],
            "flows": [item.__dict__ for item in self.flows],
            "candidates": [_strategy_json(item) for item in self.candidates],
            "backtests": [_backtest_json(item) for item in self.backtests],
            "comparisons": [item.__dict__ | {"decision": item.decision.value} for item in self.comparisons],
            "improved_candidates": [_strategy_json(item) for item in self.improved_candidates],
            "evolution_winners": [_strategy_json(item) for item in self.evolution_winners],
            "summary": self.summary,
            "limitations": list(self.limitations),
        }


class KRXMarketDataTool:
    def fetch(self, *, symbol: str = "KOSPI", days: int = 20, retrieved_at: str | None = None) -> dict[str, object]:
        if days < 1 or days > 250:
            raise ValueError("KRX market data days must be between 1 and 250")
        at = retrieved_at or utc_now()
        bars = _fixture_bars(symbol.upper(), days, at)
        return {
            "provider": "krx-fixture",
            "retrieved_at": at,
            "symbol": symbol.upper(),
            "bars": [bar.to_json() for bar in bars],
            "fields": ["OHLC", "volume", "trading_value", "market_cap", "foreign", "institution", "pension", "program", "short_sale"],
            "warnings": ["fixture data only; no live KRX network request was made"],
        }


class NewsAnalysisEngine:
    def analyze(self, items: tuple[NewsItem, ...]) -> tuple[NewsAnalysis, ...]:
        analyses: list[NewsAnalysis] = []
        for item in items:
            text = f"{item.title} {item.body}".casefold()
            score = _clip_score(sum(2 for token in ("surge", "beat", "growth", "수주", "강세") if token in text) - sum(2 for token in ("risk", "miss", "probe", "약세") if token in text))
            label = "positive" if score > 0 else "negative" if score < 0 else "neutral"
            analyses.append(NewsAnalysis(item.symbol, item.theme, label, score, (item.source.citation_id,)))
        return tuple(analyses)


class ThemeAnalysisEngine:
    def analyze(self, news: tuple[NewsAnalysis, ...], bars: tuple[KRXMarketBar, ...]) -> tuple[ThemeAnalysis, ...]:
        by_theme: dict[str, list[NewsAnalysis]] = {}
        for item in news:
            by_theme.setdefault(item.theme, []).append(item)
        close_return = ((bars[-1].close - bars[0].close) / bars[0].close) if len(bars) > 1 else 0.0
        results: list[ThemeAnalysis] = []
        for theme, items in sorted(by_theme.items()):
            score = sum(item.score for item in items) + close_return * 10
            strength = ThemeStrength.LEADER if score >= 3 else ThemeStrength.FOLLOWER if score >= 0 else ThemeStrength.WEAK
            symbols = tuple(sorted({item.symbol for item in items}))
            results.append(ThemeAnalysis(theme, strength, symbols[:1], symbols[1:], round(score, 4)))
        return tuple(results)


class FlowAnalysisEngine:
    def analyze(self, bars: tuple[KRXMarketBar, ...]) -> FlowAnalysis:
        if not bars:
            raise ValueError("flow analysis requires market bars")
        last5 = bars[-5:]
        last20 = bars[-20:]
        foreign_5d = sum(bar.foreign_net_buy for bar in last5)
        institution_5d = sum(bar.institution_net_buy for bar in last5)
        program_5d = sum(bar.program_net_buy for bar in last5)
        trend = "accumulation" if foreign_5d + institution_5d + program_5d > 0 else "distribution"
        return FlowAnalysis(
            bars[-1].symbol,
            foreign_5d,
            sum(bar.foreign_net_buy for bar in last20),
            institution_5d,
            sum(bar.institution_net_buy for bar in last20),
            program_5d,
            sum(bar.program_net_buy for bar in last20),
            sum(bar.short_sale_value for bar in last5),
            trend,
        )


class CandidateStrategyGenerator:
    def generate(self, themes: tuple[ThemeAnalysis, ...], flow: FlowAnalysis) -> tuple[CandidateStrategy, ...]:
        base = ("Breakout", "Momentum", "VWAP", "Opening Range", "Pullback")
        theme = themes[0].theme if themes else "market"
        strength = themes[0].strength.value if themes else "weak"
        return (
            CandidateStrategy(f"candidate:{theme}:breakout-momentum", ("Breakout", "Momentum", "Volume Filter"), {"breakout_period": 20, "flow_trend": flow.trend, "theme_strength": strength}, "Trade confirmed breakouts only when theme and supply-demand align."),
            CandidateStrategy(f"candidate:{theme}:gap-vwap", ("Gap", "VWAP", "Opening Range"), {"gap_min_pct": 2.0, "vwap_confirmation": True, "max_entry_minutes": 30}, "Use opening gaps with VWAP confirmation and bounded intraday assumptions."),
            CandidateStrategy(f"candidate:{theme}:pullback", base[-2:], {"ma_filter": "20d", "pullback_depth_pct": 3.0}, "Prefer pullbacks in strong themes instead of chasing extended moves."),
        )


class AutomatedBacktestResearchEngine:
    def run(self, candidates: tuple[CandidateStrategy, ...]) -> tuple[ResearchBacktest, ...]:
        horizons = ("5y", "3y", "1y", "6m")
        reports: list[ResearchBacktest] = []
        for candidate_index, candidate in enumerate(candidates):
            for horizon_index, horizon in enumerate(horizons):
                edge = 0.04 + candidate_index * 0.015 - horizon_index * 0.003
                reports.append(
                    ResearchBacktest(
                        candidate.strategy_id,
                        horizon,
                        BacktestMetrics(total_return=edge * 2, annualized_return=edge, max_drawdown=0.08 + horizon_index * 0.01, win_rate=0.51 + candidate_index * 0.02, profit_factor=1.15 + candidate_index * 0.12, sharpe_ratio=0.8 + candidate_index * 0.25, trade_count=48 - horizon_index * 4, average_trade_return=0.002 + candidate_index * 0.0005, exposure=0.45),
                        {"commission": 0.00015, "tax": 0.0018, "slippage": 0.0005},
                    )
                )
        return tuple(reports)


class PerformanceComparator:
    def compare(self, backtests: tuple[ResearchBacktest, ...], *, champion_sharpe: float = 0.9) -> tuple[StrategyComparison, ...]:
        grouped: dict[str, list[ResearchBacktest]] = {}
        for item in backtests:
            grouped.setdefault(item.strategy_id, []).append(item)
        comparisons: list[StrategyComparison] = []
        for strategy_id, items in sorted(grouped.items()):
            sharpe = _avg(item.metrics.sharpe_ratio for item in items)
            mdd = _avg(item.metrics.max_drawdown for item in items)
            win_rate = _avg(item.metrics.win_rate for item in items)
            profit_factor = _avg(item.metrics.profit_factor for item in items)
            expectancy = _avg(item.metrics.average_trade_return for item in items)
            decision = ResearchDecision.RECOMMEND if sharpe > champion_sharpe and profit_factor >= 1.2 and mdd <= 0.2 else ResearchDecision.NEEDS_MORE_VALIDATION if profit_factor >= 1.1 else ResearchDecision.REJECT
            comparisons.append(StrategyComparison(strategy_id, decision, round(sharpe, 4), round(mdd, 4), round(win_rate, 4), round(profit_factor, 4), round(expectancy, 6), round(sharpe - champion_sharpe, 4)))
        return tuple(comparisons)


class StrategyImprover:
    def improve(self, candidates: tuple[CandidateStrategy, ...], comparisons: tuple[StrategyComparison, ...]) -> tuple[CandidateStrategy, ...]:
        weak = {item.strategy_id for item in comparisons if item.decision is not ResearchDecision.RECOMMEND}
        improved: list[CandidateStrategy] = []
        for candidate in candidates:
            if candidate.strategy_id in weak:
                params = dict(candidate.parameters)
                params["risk_pct"] = 0.01
                params["avoid_low_liquidity"] = True
                improved.append(CandidateStrategy(f"{candidate.strategy_id}:improved", candidate.components + ("Risk Filter",), params, f"Improve low performance cause by tightening risk and liquidity filters: {candidate.hypothesis}"))
        return tuple(improved)


class EvolutionEngine:
    def evolve(self, candidates: tuple[CandidateStrategy, ...], comparisons: tuple[StrategyComparison, ...], *, max_winners: int = 2) -> tuple[CandidateStrategy, ...]:
        ranked = sorted(comparisons, key=lambda item: (item.sharpe, item.profit_factor, -item.mdd), reverse=True)
        top_ids = {item.strategy_id for item in ranked[:max_winners]}
        winners = [candidate for candidate in candidates if candidate.strategy_id in top_ids]
        if len(winners) >= 2:
            child_params = dict(winners[0].parameters) | {"mutation": "lower_breakout_period", "parent_b": winners[1].strategy_id}
            winners.append(CandidateStrategy("candidate:evolved:hybrid", tuple(sorted(set(winners[0].components + winners[1].components))), child_params, "Hybrid evolved from top ranked strategies with bounded mutation."))
        return tuple(winners[: max_winners + 1])


class AIResearchReporter:
    def build(self, *, report_id: str, generated_at: str, market_sources: tuple[str, ...], news: tuple[NewsAnalysis, ...], themes: tuple[ThemeAnalysis, ...], flows: tuple[FlowAnalysis, ...], candidates: tuple[CandidateStrategy, ...], backtests: tuple[ResearchBacktest, ...], comparisons: tuple[StrategyComparison, ...], improved: tuple[CandidateStrategy, ...], winners: tuple[CandidateStrategy, ...]) -> AIResearchReport:
        best = winners[0].strategy_id if winners else "none"
        return AIResearchReport(
            report_id,
            generated_at,
            market_sources,
            news,
            themes,
            flows,
            candidates,
            backtests,
            comparisons,
            improved,
            winners,
            f"AI Quant Research completed with {len(candidates)} candidates; best advisory candidate is {best}. Champion promotion remains disabled.",
            ("fixture KRX data only", "no automatic order", "no automatic Champion promotion", "all external data requires source/freshness review"),
        )


class QuantResearchOrchestrator:
    def run(self, *, symbol: str = "KOSPI", report_id: str = "quant-research-demo", generated_at: str | None = None) -> AIResearchReport:
        at = generated_at or utc_now()
        market = KRXMarketDataTool().fetch(symbol=symbol, days=20, retrieved_at=at)
        bars = tuple(_bar_from_json(item) for item in market["bars"])  # type: ignore[index]
        news_items = _fixture_news(symbol.upper(), at)
        news = NewsAnalysisEngine().analyze(news_items)
        themes = ThemeAnalysisEngine().analyze(news, bars)
        flow = FlowAnalysisEngine().analyze(bars)
        candidates = CandidateStrategyGenerator().generate(themes, flow)
        backtests = AutomatedBacktestResearchEngine().run(candidates)
        comparisons = PerformanceComparator().compare(backtests)
        improved = StrategyImprover().improve(candidates, comparisons)
        winners = EvolutionEngine().evolve(candidates + improved, comparisons)
        return AIResearchReporter().build(report_id=report_id, generated_at=at, market_sources=(str(market["provider"]),), news=news, themes=themes, flows=(flow,), candidates=candidates, backtests=backtests, comparisons=comparisons, improved=improved, winners=winners)


class SQLiteQuantResearchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_report(self, report: AIResearchReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO quant_research_reports(report_id, payload_json, generated_at) VALUES (?, ?, ?) ON CONFLICT(report_id) DO UPDATE SET payload_json=excluded.payload_json, generated_at=excluded.generated_at",
                (report.report_id, json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")), report.generated_at),
            )


def _fixture_bars(symbol: str, days: int, retrieved_at: str) -> tuple[KRXMarketBar, ...]:
    source = SourceProvenance("krx-fixture", "https://data.krx.co.kr/", "data.krx.co.kr", retrieved_at, retrieved_at, TrustClassification.OFFICIAL, FreshnessStatus.FRESH)
    bars: list[KRXMarketBar] = []
    for index in range(days):
        close = 100.0 + index * 0.8
        bars.append(KRXMarketBar(symbol, f"2026-07-{index + 1:02d}", close - 0.7, close + 1.4, close - 1.2, close, 1_000_000 + index * 10_000, 100_000_000_000 + index * 1_000_000_000, 50_000_000_000_000, 1_000_000 + index * 25_000, 500_000 + index * 15_000, 100_000 + index * 5_000, 200_000 + index * 8_000, 50_000_000 - index * 500_000, source))
    return tuple(bars)


def _fixture_news(symbol: str, at: str) -> tuple[NewsItem, ...]:
    source = SourceProvenance("news-fixture-1", "https://example.com/news/ai-semiconductor", "example.com", at, at, TrustClassification.NEWS, FreshnessStatus.FRESH)
    return (
        NewsItem("AI semiconductor growth beat", "AI and HBM chip demand surge with positive order momentum.", symbol, "semiconductor", source),
        NewsItem("Robot automation theme expands", "Factory automation and robot adoption show neutral but improving trend.", symbol, "robot", source),
    )


def _bar_from_json(payload: dict[str, object]) -> KRXMarketBar:
    ohlc = payload["ohlc"]  # type: ignore[index]
    source_payload = payload["source"]  # type: ignore[index]
    source = SourceProvenance(str(source_payload["citation_id"]), str(source_payload["canonical_url"]), str(source_payload["domain"]), str(source_payload["published_at"]) if source_payload.get("published_at") else None, str(source_payload["retrieved_at"]), TrustClassification(str(source_payload["trust"])), FreshnessStatus(str(source_payload["freshness"])))  # type: ignore[index]
    return KRXMarketBar(str(payload["symbol"]), str(payload["date"]), float(ohlc["open"]), float(ohlc["high"]), float(ohlc["low"]), float(ohlc["close"]), int(payload["volume"]), int(payload["trading_value"]), int(payload["market_cap"]), int(payload["foreign_net_buy"]), int(payload["institution_net_buy"]), int(payload["pension_net_buy"]), int(payload["program_net_buy"]), int(payload["short_sale_value"]), source)  # type: ignore[index]


def _strategy_json(strategy: CandidateStrategy) -> dict[str, object]:
    return {"strategy_id": strategy.strategy_id, "components": list(strategy.components), "parameters": dict(sorted(strategy.parameters.items())), "hypothesis": strategy.hypothesis}


def _backtest_json(backtest: ResearchBacktest) -> dict[str, object]:
    return {"strategy_id": backtest.strategy_id, "horizon": backtest.horizon, "metrics": backtest.metrics.__dict__, "cost_model": dict(sorted(backtest.cost_model.items()))}


def _clip_score(value: int) -> int:
    return max(-5, min(5, value))


def _avg(values) -> float:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else 0.0


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
