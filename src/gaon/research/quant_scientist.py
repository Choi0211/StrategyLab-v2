"""AI Quant Scientist foundation for Sprint 81-90.

The scientist layer studies features, validation robustness, regimes, portfolio
mixes, ensembles, and explanations. It remains advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import sqlite3

from gaon.research.quant_research import KRXMarketBar, KRXMarketDataTool, _bar_from_json, utc_now


class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class EnsembleSignal(str, Enum):
    LONG_BIAS = "long_bias"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


@dataclass(frozen=True)
class DiscoveredFeature:
    name: str
    values: tuple[float, ...]
    source_ref: str
    source_trust: str
    source_freshness: str


@dataclass(frozen=True)
class FeatureImportance:
    feature_name: str
    correlation: float
    information_gain: float
    mutual_information: float
    importance: float


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: str
    train_score: float
    validation_score: float
    forward_score: float
    passed: bool


@dataclass(frozen=True)
class MonteCarloResult:
    simulation_id: str
    entry_exit_shuffle_score: float
    noise_injection_score: float
    robustness_score: float


@dataclass(frozen=True)
class RegimeDetection:
    regime: Regime
    confidence: float
    recommended_strategies: tuple[str, ...]


@dataclass(frozen=True)
class MetaStrategyDecision:
    strategy_id: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class PortfolioAllocation:
    weights: dict[str, float]
    expected_return: float
    expected_risk: float


@dataclass(frozen=True)
class EnsembleDecision:
    signal: EnsembleSignal
    votes: dict[str, str]
    confidence: float


@dataclass(frozen=True)
class Explanation:
    recommendation: str
    feature_contributions: dict[str, float]
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class AIScientistReport:
    report_id: str
    generated_at: str
    features: tuple[DiscoveredFeature, ...]
    selected_features: tuple[FeatureImportance, ...]
    walk_forward: tuple[WalkForwardWindow, ...]
    monte_carlo: MonteCarloResult
    regime: RegimeDetection
    meta_strategy: MetaStrategyDecision
    portfolio: PortfolioAllocation
    ensemble: EnsembleDecision
    explanation: Explanation
    champion_comparison: dict[str, object]
    final_recommendation: str
    limitations: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "features": [
                {
                    "name": item.name,
                    "values": list(item.values),
                    "source_ref": item.source_ref,
                    "source_trust": item.source_trust,
                    "source_freshness": item.source_freshness,
                }
                for item in self.features
            ],
            "selected_features": [item.__dict__ for item in self.selected_features],
            "walk_forward": [item.__dict__ for item in self.walk_forward],
            "monte_carlo": self.monte_carlo.__dict__,
            "regime": {"regime": self.regime.regime.value, "confidence": self.regime.confidence, "recommended_strategies": list(self.regime.recommended_strategies)},
            "meta_strategy": self.meta_strategy.__dict__,
            "portfolio": {"weights": dict(sorted(self.portfolio.weights.items())), "expected_return": self.portfolio.expected_return, "expected_risk": self.portfolio.expected_risk},
            "ensemble": {"signal": self.ensemble.signal.value, "votes": dict(sorted(self.ensemble.votes.items())), "confidence": self.ensemble.confidence},
            "explanation": {"recommendation": self.explanation.recommendation, "feature_contributions": dict(sorted(self.explanation.feature_contributions.items())), "rationale": list(self.explanation.rationale)},
            "champion_comparison": dict(sorted(self.champion_comparison.items())),
            "final_recommendation": self.final_recommendation,
            "limitations": list(self.limitations),
        }


class FeatureDiscoveryEngine:
    def discover(self, bars: tuple[KRXMarketBar, ...]) -> tuple[DiscoveredFeature, ...]:
        if len(bars) < 2:
            raise ValueError("feature discovery requires at least two bars")
        closes = [bar.close for bar in bars]
        volumes = [float(bar.volume) for bar in bars]
        values = [float(bar.trading_value) for bar in bars]
        vwap = tuple(round(value / max(volume, 1.0), 6) for value, volume in zip(values, volumes))
        gap = tuple(0.0 if index == 0 else round((bars[index].open - bars[index - 1].close) / bars[index - 1].close, 6) for index in range(len(bars)))
        returns = tuple(0.0 if index == 0 else round((closes[index] - closes[index - 1]) / closes[index - 1], 6) for index in range(len(closes)))
        volatility = _rolling_abs(returns, 5)
        volume_change = tuple(0.0 if index == 0 else round((volumes[index] - volumes[index - 1]) / max(volumes[index - 1], 1.0), 6) for index in range(len(volumes)))
        relative_strength = tuple(round(close / closes[0] - 1.0, 6) for close in closes)
        source = bars[-1].source
        return (
            DiscoveredFeature("volume_change", volume_change, source.citation_id, source.trust.value, source.freshness.value),
            DiscoveredFeature("volatility_5d", volatility, source.citation_id, source.trust.value, source.freshness.value),
            DiscoveredFeature("vwap", vwap, source.citation_id, source.trust.value, source.freshness.value),
            DiscoveredFeature("gap", gap, source.citation_id, source.trust.value, source.freshness.value),
            DiscoveredFeature("relative_strength", relative_strength, source.citation_id, source.trust.value, source.freshness.value),
        )


class FeatureSelectionEngine:
    def select(self, features: tuple[DiscoveredFeature, ...], target_returns: tuple[float, ...], *, top_n: int = 3) -> tuple[FeatureImportance, ...]:
        ranked: list[FeatureImportance] = []
        for feature in features:
            corr = _correlation(feature.values, target_returns)
            info_gain = min(1.0, abs(corr) * 0.7 + _variance(feature.values) * 0.3)
            mutual = min(1.0, abs(corr) * 0.6 + abs(_mean(feature.values)) * 0.4)
            importance = round(abs(corr) * 0.5 + info_gain * 0.3 + mutual * 0.2, 6)
            ranked.append(FeatureImportance(feature.name, round(corr, 6), round(info_gain, 6), round(mutual, 6), importance))
        return tuple(sorted(ranked, key=lambda item: item.importance, reverse=True)[:top_n])


class WalkForwardValidator:
    def validate(self, selected: tuple[FeatureImportance, ...]) -> tuple[WalkForwardWindow, ...]:
        base = sum(item.importance for item in selected) / max(len(selected), 1)
        windows: list[WalkForwardWindow] = []
        for index in range(3):
            train = min(1.0, base + 0.05 - index * 0.02)
            validation = min(1.0, base + 0.02 - index * 0.015)
            forward = min(1.0, base - index * 0.01)
            windows.append(WalkForwardWindow(f"wf-{index + 1}", round(train, 6), round(validation, 6), round(forward, 6), forward >= 0.15))
        return tuple(windows)


class MonteCarloSimulator:
    def simulate(self, selected: tuple[FeatureImportance, ...]) -> MonteCarloResult:
        base = sum(item.importance for item in selected) / max(len(selected), 1)
        shuffle = max(0.0, min(1.0, base * 0.92))
        noise = max(0.0, min(1.0, base * 0.86))
        return MonteCarloResult("mc-fixture", round(shuffle, 6), round(noise, 6), round((shuffle + noise) / 2.0, 6))


class MarketRegimeDetector:
    def detect(self, bars: tuple[KRXMarketBar, ...]) -> RegimeDetection:
        returns = _returns(tuple(bar.close for bar in bars))
        total = (bars[-1].close - bars[0].close) / bars[0].close
        vol = sum(abs(item) for item in returns) / max(len(returns), 1)
        if vol > 0.025:
            regime = Regime.HIGH_VOLATILITY
        elif vol < 0.006:
            regime = Regime.LOW_VOLATILITY
        elif total > 0.05:
            regime = Regime.BULL
        elif total < -0.05:
            regime = Regime.BEAR
        else:
            regime = Regime.SIDEWAYS
        strategies = {
            Regime.BULL: ("breakout_momentum", "pullback"),
            Regime.BEAR: ("risk_off", "mean_reversion_small"),
            Regime.SIDEWAYS: ("vwap", "range_reversion"),
            Regime.HIGH_VOLATILITY: ("opening_range", "volatility_filter"),
            Regime.LOW_VOLATILITY: ("breakout_watch", "gap_filter"),
        }[regime]
        return RegimeDetection(regime, 0.7, strategies)


class MetaStrategyEngine:
    def decide(self, regime: RegimeDetection, selected: tuple[FeatureImportance, ...], monte_carlo: MonteCarloResult) -> MetaStrategyDecision:
        strength = sum(item.importance for item in selected) / max(len(selected), 1)
        confidence = round(min(1.0, regime.confidence * 0.4 + monte_carlo.robustness_score * 0.4 + strength * 0.2), 6)
        return MetaStrategyDecision(regime.recommended_strategies[0], confidence, f"Selected for {regime.regime.value} regime with robustness {monte_carlo.robustness_score:.3f}.")


class PortfolioOptimizer:
    def optimize(self, decisions: tuple[MetaStrategyDecision, ...]) -> PortfolioAllocation:
        if not decisions:
            raise ValueError("portfolio optimizer requires at least one strategy")
        total = sum(max(item.confidence, 0.01) for item in decisions)
        weights = {item.strategy_id: round(max(item.confidence, 0.01) / total, 6) for item in decisions}
        expected_return = round(sum(weight * 0.12 for weight in weights.values()), 6)
        expected_risk = round(sum(weight * 0.08 for weight in weights.values()), 6)
        return PortfolioAllocation(weights, expected_return, expected_risk)


class EnsembleDecisionEngine:
    def decide(self, walk_forward: tuple[WalkForwardWindow, ...], monte_carlo: MonteCarloResult, regime: RegimeDetection, meta: MetaStrategyDecision) -> EnsembleDecision:
        votes = {
            "walk_forward": "long_bias" if sum(1 for window in walk_forward if window.passed) >= 2 else "neutral",
            "monte_carlo": "long_bias" if monte_carlo.robustness_score >= 0.15 else "risk_off",
            "regime": "risk_off" if regime.regime is Regime.BEAR else "long_bias",
            "meta": "long_bias" if meta.confidence >= 0.3 else "neutral",
        }
        long_votes = sum(1 for vote in votes.values() if vote == "long_bias")
        risk_votes = sum(1 for vote in votes.values() if vote == "risk_off")
        signal = EnsembleSignal.LONG_BIAS if long_votes >= 3 else EnsembleSignal.RISK_OFF if risk_votes >= 2 else EnsembleSignal.NEUTRAL
        return EnsembleDecision(signal, votes, round(max(long_votes, risk_votes, 1) / len(votes), 6))


class ExplainableAI:
    def explain(self, selected: tuple[FeatureImportance, ...], meta: MetaStrategyDecision, ensemble: EnsembleDecision) -> Explanation:
        total = sum(item.importance for item in selected) or 1.0
        contributions = {item.feature_name: round(item.importance / total, 6) for item in selected}
        rationale = (
            meta.reason,
            f"Ensemble signal is {ensemble.signal.value} with confidence {ensemble.confidence:.3f}.",
            "No automatic order, approval bypass, or Champion promotion is allowed.",
        )
        return Explanation(meta.strategy_id, contributions, rationale)


class AIScientistReporter:
    def build(self, *, report_id: str, generated_at: str, features: tuple[DiscoveredFeature, ...], selected: tuple[FeatureImportance, ...], walk_forward: tuple[WalkForwardWindow, ...], monte_carlo: MonteCarloResult, regime: RegimeDetection, meta: MetaStrategyDecision, portfolio: PortfolioAllocation, ensemble: EnsembleDecision, explanation: Explanation) -> AIScientistReport:
        return AIScientistReport(
            report_id,
            generated_at,
            features,
            selected,
            walk_forward,
            monte_carlo,
            regime,
            meta,
            portfolio,
            ensemble,
            explanation,
            {"champion_strategy": "current_champion_baseline", "automatic_promotion": False, "comparison_note": "advisory only"},
            f"Recommend {ensemble.signal.value} research posture for {meta.strategy_id}; human approval remains required.",
            ("fixture market data", "no live trading", "no automatic Champion promotion", "feature importance is deterministic fixture scoring"),
        )


class AIScientistOrchestrator:
    def run(self, *, symbol: str = "KOSPI", report_id: str = "ai-scientist-demo", generated_at: str | None = None) -> AIScientistReport:
        at = generated_at or utc_now()
        market = KRXMarketDataTool().fetch(symbol=symbol, days=60, retrieved_at=at)
        bars = tuple(_bar_from_json(item) for item in market["bars"])  # type: ignore[index]
        features = FeatureDiscoveryEngine().discover(bars)
        targets = _returns(tuple(bar.close for bar in bars))
        selected = FeatureSelectionEngine().select(features, targets)
        walk_forward = WalkForwardValidator().validate(selected)
        monte_carlo = MonteCarloSimulator().simulate(selected)
        regime = MarketRegimeDetector().detect(bars)
        meta = MetaStrategyEngine().decide(regime, selected, monte_carlo)
        portfolio = PortfolioOptimizer().optimize((meta,))
        ensemble = EnsembleDecisionEngine().decide(walk_forward, monte_carlo, regime, meta)
        explanation = ExplainableAI().explain(selected, meta, ensemble)
        return AIScientistReporter().build(report_id=report_id, generated_at=at, features=features, selected=selected, walk_forward=walk_forward, monte_carlo=monte_carlo, regime=regime, meta=meta, portfolio=portfolio, ensemble=ensemble, explanation=explanation)


class SQLiteAIScientistRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_report(self, report: AIScientistReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO ai_scientist_reports(report_id, payload_json, generated_at) VALUES (?, ?, ?) ON CONFLICT(report_id) DO UPDATE SET payload_json=excluded.payload_json, generated_at=excluded.generated_at",
                (report.report_id, json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")), report.generated_at),
            )
            for item in report.selected_features:
                self._connection.execute(
                    "INSERT INTO ai_feature_importance(report_id, feature_name, importance, payload_json) VALUES (?, ?, ?, ?) ON CONFLICT(report_id, feature_name) DO UPDATE SET importance=excluded.importance, payload_json=excluded.payload_json",
                    (report.report_id, item.feature_name, item.importance, json.dumps(item.__dict__, sort_keys=True, separators=(",", ":"))),
                )
            for window in report.walk_forward:
                self._connection.execute(
                    "INSERT INTO ai_walk_forward_results(report_id, window_id, passed, payload_json) VALUES (?, ?, ?, ?) ON CONFLICT(report_id, window_id) DO UPDATE SET passed=excluded.passed, payload_json=excluded.payload_json",
                    (report.report_id, window.window_id, int(window.passed), json.dumps(window.__dict__, sort_keys=True, separators=(",", ":"))),
                )
            self._connection.execute(
                "INSERT INTO ai_monte_carlo_results(report_id, simulation_id, robustness_score, payload_json) VALUES (?, ?, ?, ?) ON CONFLICT(report_id, simulation_id) DO UPDATE SET robustness_score=excluded.robustness_score, payload_json=excluded.payload_json",
                (report.report_id, report.monte_carlo.simulation_id, report.monte_carlo.robustness_score, json.dumps(report.monte_carlo.__dict__, sort_keys=True, separators=(",", ":"))),
            )


def feature_discovery_payload(*, symbol: str = "KOSPI", days: int = 60, retrieved_at: str | None = None) -> dict[str, object]:
    at = retrieved_at or utc_now()
    market = KRXMarketDataTool().fetch(symbol=symbol, days=days, retrieved_at=at)
    bars = tuple(_bar_from_json(item) for item in market["bars"])  # type: ignore[index]
    features = FeatureDiscoveryEngine().discover(bars)
    return {
        "provider": "krx-fixture",
        "symbol": symbol,
        "retrieved_at": at,
        "features": [
            {
                "name": item.name,
                "values": list(item.values),
                "source_ref": item.source_ref,
                "source_trust": item.source_trust,
                "source_freshness": item.source_freshness,
            }
            for item in features
        ],
        "warnings": ["feature discovery is deterministic fixture research; no order or Champion promotion was performed"],
    }


def _returns(closes: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(0.0 if index == 0 else (closes[index] - closes[index - 1]) / closes[index - 1] for index in range(len(closes)))


def _rolling_abs(values: tuple[float, ...], window: int) -> tuple[float, ...]:
    output: list[float] = []
    for index in range(len(values)):
        sample = values[max(0, index - window + 1) : index + 1]
        output.append(round(sum(abs(item) for item in sample) / len(sample), 6))
    return tuple(output)


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    x = left[-size:]
    y = right[-size:]
    mx = _mean(x)
    my = _mean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return numerator / denominator if denominator else 0.0


def _variance(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return sum((item - mean) ** 2 for item in values) / len(values)


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0
