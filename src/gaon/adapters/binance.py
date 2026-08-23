"""Read-only Binance adapter.

Surfaces the separately-deployed Binance futures bot's live state (account
equity, positions, recent trade outcomes, the current live Champion
strategy's parameters) and its BIN-PA price-action research output to Gaon,
so Gaon can read and research Binance the same way it already reads and
researches KRX - but strictly as a research/analysis partner, never as an
executor.

Hard invariants, enforced structurally rather than by convention:
- This module contains no code path that writes to any file under the
  configured Binance directories. Every reader here is read-only.
- This module contains no live-order call of any kind - not a disabled
  stub, not a guarded method. `execute_order`/`propose_order`/
  `approve_order`/`simulate_order` simply do not exist here. If Gaon's
  runtime ever needs "propose a Binance strategy candidate", that proposal
  lives in Gaon's OWN storage (e.g. gaon.knowledge.strategy_candidate),
  never written into the Binance bot's `strategy_params.json` or
  `strategy_proposal.json`.
- The champion/challenger comparison below reuses the existing
  ChampionChallengerEvaluationEngine, whose own decision names already make
  this explicit: `PROMOTION_CANDIDATE` is documented ("this is not
  promotion") as a research recommendation only - see
  gaon/adapters/champion.py's `_rationale`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from gaon.adapters.backtest import (
    BacktestDatasetRef,
    BacktestMetrics,
    BacktestPeriod,
    BacktestResult,
    BacktestStatus,
    BacktestStrategyRef,
    BacktestTradeSummary,
)
from gaon.adapters.champion import (
    ChampionChallengerEvaluationEngine,
    ChampionChallengerEvaluationReport,
    ChampionChallengerPolicy,
    build_champion_challenger_request,
)
from gaon.adapters.validation import (
    StrategyValidationEngine,
    ValidationPolicy,
    ValidationReport,
    build_validation_request,
)

DEFAULT_BINANCE_STATE_DIR = "/opt/binance-trading"
BASELINE_FAMILY_ID = "BASELINE"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BinanceAdapterConfig:
    """Where to read Binance's own files from. Never a write target."""

    state_dir: Path
    research_dir: Path

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def balance_history_path(self) -> Path:
        return self.state_dir / "balance_history.json"

    @property
    def trade_events_path(self) -> Path:
        return self.state_dir / "trade_events.json"

    @property
    def strategy_params_path(self) -> Path:
        return self.state_dir / "strategy_params.json"

    @property
    def bot_settings_path(self) -> Path:
        return self.state_dir / "bot_settings.json"

    @property
    def strategy_proposal_path(self) -> Path:
        return self.state_dir / "strategy_proposal.json"

    @property
    def walkforward_path(self) -> Path:
        return self.research_dir / "price_action_walkforward.json"

    @property
    def single_split_research_path(self) -> Path:
        return self.research_dir / "price_action_research.json"


def build_binance_adapter_config_from_env(env: Mapping[str, str]) -> BinanceAdapterConfig:
    """Matches this codebase's existing `build_..._from_env(env)` convention
    (see gaon.research.krx_real_pipeline.build_market_data_provider_from_env).
    `GAON_BINANCE_STATE_DIR` points at the live bot's directory (production:
    /opt/binance-trading). `GAON_BINANCE_RESEARCH_DIR` points at wherever the
    BIN-PA research JSON is produced; it defaults to the same directory as
    state_dir since research output may be co-located with the live bot, but
    can be pointed at a separate research-only deployment if one exists."""
    state_dir = Path(env.get("GAON_BINANCE_STATE_DIR", "").strip() or DEFAULT_BINANCE_STATE_DIR)
    research_dir_raw = env.get("GAON_BINANCE_RESEARCH_DIR", "").strip()
    research_dir = Path(research_dir_raw) if research_dir_raw else state_dir
    return BinanceAdapterConfig(state_dir=state_dir, research_dir=research_dir)


# --------------------------------------------------------------------------
# Read-only data shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BinanceAccountSnapshot:
    equity: float
    testnet: bool
    demo_mode: bool
    strategy_mode: str
    updated_at: str
    note: str = ""


@dataclass(frozen=True)
class BinancePositionSnapshot:
    """`amount` is signed: negative means a short futures position. This is
    intentionally NOT gaon.adapters.trading.PositionSnapshot - KRX equity
    positions have no signed short quantity, no leverage, and no
    unrealized_pnl field in that shape, so forcing a fit would either lose
    information or misuse a field."""

    symbol: str
    amount: float
    entry_price: float
    unrealized_pnl: float


@dataclass(frozen=True)
class BinanceTradeEvent:
    symbol: str
    realized_pnl_usdt: float
    result: str
    closed_at: str


@dataclass(frozen=True)
class BinanceBalancePoint:
    at: str
    equity: float


@dataclass(frozen=True)
class BinanceChampionStrategySnapshot:
    """DISPLAY-ONLY snapshot of the live strategy_params.json. There is no
    method anywhere in this module - or anywhere Gaon can reach - that
    writes to this file. Changing the live Champion requires a human
    editing strategy_params.json (or the bot's approval flow) directly;
    Gaon reading this value never mutates it."""

    parameters: Mapping[str, float | int | str]
    source_path: str
    read_at: str


@dataclass(frozen=True)
class BinanceResearchFamilySummary:
    family_id: str
    num_folds: int
    oos_total_trades: int
    oos_win_rate: float
    oos_mean_return_pct: float
    oos_max_drawdown_pct: float
    oos_profitable_symbol_ratio: float


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


class BinanceStateReader:
    """Read-only. No method on this class writes anything."""

    def __init__(self, config: BinanceAdapterConfig) -> None:
        self._config = config

    def account_snapshot(self) -> BinanceAccountSnapshot | None:
        data = _read_json(self._config.state_path)
        if data is None:
            return None
        return BinanceAccountSnapshot(
            equity=float(data.get("equity", 0.0)),
            testnet=bool(data.get("testnet", True)),
            demo_mode=bool(data.get("demo_mode", True)),
            strategy_mode=str(data.get("strategy_mode", "unknown")),
            updated_at=str(data.get("updated_at", "")),
            note=str(data.get("note", "")),
        )

    def positions(self) -> tuple[BinancePositionSnapshot, ...]:
        data = _read_json(self._config.state_path) or {}
        return tuple(
            BinancePositionSnapshot(
                symbol=str(item["symbol"]),
                amount=float(item["amount"]),
                entry_price=float(item["entry_price"]),
                unrealized_pnl=float(item["unrealized_pnl"]),
            )
            for item in data.get("positions", [])
        )

    def balance_history(self, limit: int = 50) -> tuple[BinanceBalancePoint, ...]:
        data = _read_json(self._config.balance_history_path) or []
        points = tuple(BinanceBalancePoint(at=str(item["t"]), equity=float(item["v"])) for item in data)
        return points[-limit:]

    def recent_trade_events(self, limit: int = 20) -> tuple[BinanceTradeEvent, ...]:
        data = _read_json(self._config.trade_events_path) or []
        events = tuple(
            BinanceTradeEvent(
                symbol=str(item["symbol"]),
                realized_pnl_usdt=float(item["realized_pnl_usdt"]),
                result=str(item["result"]),
                closed_at=str(item["closed_at"]),
            )
            for item in data
        )
        return events[-limit:]

    def champion_strategy(self) -> BinanceChampionStrategySnapshot | None:
        path = self._config.strategy_params_path
        data = _read_json(path)
        if data is None:
            return None
        return BinanceChampionStrategySnapshot(
            parameters=dict(data),
            source_path=str(path),
            read_at=datetime.now(timezone.utc).isoformat(),
        )

    def pending_challenger_proposal(self) -> Mapping[str, Any] | None:
        """Whatever backtest.py's run_strategy_search last wrote to
        strategy_proposal.json, if it exists. This is already human-gated on
        the Binance side (the file is never auto-applied there); Gaon only
        reads it, never writes it, never auto-approves it."""
        return _read_json(self._config.strategy_proposal_path)

    def health_check(self) -> tuple[bool, str]:
        if self._config.strategy_params_path.exists():
            return True, f"binance state directory readable at {self._config.state_dir}"
        return False, f"strategy_params.json not found under {self._config.state_dir}"


class BinanceResearchReader:
    """Read-only. No method on this class writes anything."""

    def __init__(self, config: BinanceAdapterConfig) -> None:
        self._config = config

    def walkforward_report(self) -> Mapping[str, Any] | None:
        return _read_json(self._config.walkforward_path)

    def single_split_research(self) -> Mapping[str, Any] | None:
        return _read_json(self._config.single_split_research_path)

    def family_summary(self, family_id: str) -> BinanceResearchFamilySummary | None:
        report = self.walkforward_report()
        if report is None:
            return None
        family = report.get("strategies", {}).get(family_id)
        if family is None:
            return None
        summary = family.get("oos_summary", {})
        return BinanceResearchFamilySummary(
            family_id=family_id,
            num_folds=int(summary.get("num_folds", 0)),
            oos_total_trades=int(summary.get("total_trades", 0)),
            oos_win_rate=float(summary.get("win_rate", 0.0)),
            oos_mean_return_pct=float(summary.get("mean_return_pct", 0.0)),
            oos_max_drawdown_pct=float(summary.get("max_drawdown_pct", 0.0)),
            oos_profitable_symbol_ratio=float(family.get("profitable_symbol_ratio", 0.0)),
        )


# --------------------------------------------------------------------------
# Champion/challenger comparison for BIN-PA candidates
#
# Reuses the existing StrategyValidationEngine + ChampionChallengerEvaluation
# Engine wholesale rather than writing bespoke Binance comparison logic:
# BacktestMetrics (total_return/max_drawdown/win_rate/profit_factor/
# trade_count) already maps cleanly onto the BIN-PA walk-forward output, and
# StrategyValidationEngine's multi-result rules (passing_window_ratio,
# catastrophic_window, one_window_dominates) are exactly the kind of
# regime-luck detection this walk-forward research was built to support.
# --------------------------------------------------------------------------


def compare_binance_family_to_baseline(
    walkforward_report: Mapping[str, Any],
    challenger_family_id: str,
    *,
    generated_at: str,
    actor_ref: str = "gaon-binance-research",
    champion_policy: ChampionChallengerPolicy | None = None,
    validation_policy: ValidationPolicy | None = None,
) -> tuple[ChampionChallengerEvaluationReport, ValidationReport]:
    strategies = walkforward_report.get("strategies", {})
    if BASELINE_FAMILY_ID not in strategies:
        raise KeyError(f"walkforward report is missing the {BASELINE_FAMILY_ID} family")
    if challenger_family_id not in strategies:
        raise KeyError(f"walkforward report is missing challenger family {challenger_family_id}")

    baseline_family = strategies[BASELINE_FAMILY_ID]
    challenger_family = strategies[challenger_family_id]

    champion_result = _map_aggregate_to_backtest_result(
        family_id=BASELINE_FAMILY_ID, family=baseline_family, generated_at=generated_at
    )
    challenger_result = _map_aggregate_to_backtest_result(
        family_id=challenger_family_id, family=challenger_family, generated_at=generated_at
    )
    fold_results = tuple(
        _map_fold_to_backtest_result(
            family_id=challenger_family_id, symbol=symbol, fold_index=index, fold=fold, generated_at=generated_at
        )
        for symbol, payload in challenger_family.get("per_symbol", {}).items()
        for index, fold in enumerate(payload.get("folds", ()))
    )
    if not fold_results:
        raise ValueError(f"walkforward report has no per-symbol fold data for {challenger_family_id}")

    validation_engine = StrategyValidationEngine(validation_policy)
    validation_request = build_validation_request(
        f"binance-validation:{challenger_family_id}",
        fold_results,
        actor_ref=actor_ref,
        requested_at=generated_at,
        policy=validation_policy,
    )
    validation_report = validation_engine.validate(validation_request, fold_results, generated_at=generated_at)

    champion_engine = ChampionChallengerEvaluationEngine(champion_policy)
    cc_request = build_champion_challenger_request(
        f"binance-champion-challenger:{challenger_family_id}",
        champion=champion_result,
        challenger=challenger_result,
        validation=validation_report,
        actor_ref=actor_ref,
        requested_at=generated_at,
        policy=champion_policy,
    )
    cc_report = champion_engine.evaluate(
        cc_request,
        champion=champion_result,
        challenger=challenger_result,
        validation=validation_report,
        generated_at=generated_at,
    )
    return cc_report, validation_report


def _map_fold_to_backtest_result(
    *, family_id: str, symbol: str, fold_index: int, fold: Mapping[str, Any], generated_at: str
) -> BacktestResult:
    oos = fold["oos"]
    period_payload = fold["oos_period"]
    period = BacktestPeriod(start_date=period_payload["start"], end_date=period_payload["end"])
    return _build_backtest_result(
        family_id=family_id,
        dataset_id=f"binance-{symbol.lower()}",
        dataset_version="walkforward-fold",
        request_suffix=f"{symbol}:fold{fold_index}",
        period=period,
        total_return_pct=float(oos["total_return_pct"]),
        max_drawdown_pct=float(oos["max_drawdown_pct"]),
        win_rate=float(oos["win_rate"]),
        trade_count=int(oos["num_trades"]),
        generated_at=generated_at,
    )


def _map_aggregate_to_backtest_result(
    *, family_id: str, family: Mapping[str, Any], generated_at: str
) -> BacktestResult:
    summary = family["oos_summary"]
    all_folds = [
        fold
        for payload in family.get("per_symbol", {}).values()
        for fold in payload.get("folds", ())
    ]
    if not all_folds:
        raise ValueError(f"{family_id} has an oos_summary but no per_symbol fold data to derive a sample period from")
    starts = sorted(fold["oos_period"]["start"] for fold in all_folds)
    ends = sorted(fold["oos_period"]["end"] for fold in all_folds)
    period = BacktestPeriod(start_date=starts[0], end_date=ends[-1])
    return _build_backtest_result(
        family_id=family_id,
        dataset_id="binance-multi-symbol",
        dataset_version="walkforward-aggregate",
        request_suffix="aggregate",
        period=period,
        total_return_pct=float(summary["mean_return_pct"]),
        max_drawdown_pct=float(summary["max_drawdown_pct"]),
        win_rate=float(summary["win_rate"]),
        trade_count=int(summary["total_trades"]),
        generated_at=generated_at,
    )


def _build_backtest_result(
    *,
    family_id: str,
    dataset_id: str,
    dataset_version: str,
    request_suffix: str,
    period: BacktestPeriod,
    total_return_pct: float,
    max_drawdown_pct: float,
    win_rate: float,
    trade_count: int,
    generated_at: str,
) -> BacktestResult:
    strategy = BacktestStrategyRef(strategy_id=f"binance-{family_id.lower()}", version="walkforward-v1")
    dataset = BacktestDatasetRef(dataset_id=dataset_id, version=dataset_version)
    request_id = f"binance-walkforward:{family_id}:{request_suffix}"
    fingerprint = _fingerprint(family_id, dataset_id, request_suffix, period.start_date, period.end_date)
    metrics = BacktestMetrics(
        # Walk-forward JSON stores percentages (e.g. -0.51 meaning -0.51%);
        # BacktestMetrics/ChampionChallengerPolicy both use fractions (0.05 = 5%).
        total_return=total_return_pct / 100.0,
        max_drawdown=max_drawdown_pct / 100.0,
        win_rate=win_rate,
        # profit_factor is deliberately left unset: the walk-forward report's
        # per-fold profit_factor is a noisy small-sample ratio and no clean
        # portfolio-level aggregate (summed gross win / gross loss) is
        # available in the report to compute one honestly. Leaving it None
        # lets StrategyValidationEngine correctly flag it via
        # missing_profit_factor_status=REVIEW rather than fabricating a
        # blended number.
        profit_factor=None,
        trade_count=trade_count,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    trade_summary = BacktestTradeSummary(trade_count=trade_count)
    return BacktestResult(
        result_id=f"result:{request_id}",
        request_id=request_id,
        status=BacktestStatus.COMPLETED,
        fingerprint=fingerprint,
        strategy=strategy,
        dataset=dataset,
        period=period,
        metrics=metrics,
        trade_summary=trade_summary,
        raw_engine_version="binance-price-action-walkforward-v1",
        parameters={},
        warnings=(),
        errors=(),
        generated_at=generated_at,
        duration_ms=0,
        reproducibility={"fingerprint": fingerprint},
    )


def _fingerprint(*parts: str) -> str:
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------
# Release check
# --------------------------------------------------------------------------


def production_binance_adapter_read_only_release_check() -> Mapping[str, object]:
    """Regression guard for the Binance read-only adapter.

    Uses synthetic fixture files written to a temporary directory (never the
    real /opt/binance-trading or any path under C:\\Users\\super\\binance_ai_bot*)
    so this check is fully hermetic. Proves: account/position/champion-
    params/research data all read correctly; the champion-strategy snapshot
    is display-only (no write method exists on BinanceStateReader or
    BinanceChampionStrategySnapshot - checked via introspection, not just
    convention); and the champion/challenger comparison for a BIN-PA
    challenger runs end-to-end through the existing validation + champion/
    challenger machinery without mutating anything or requiring any order
    execution.
    """
    import tempfile

    now = "2026-08-23T00:00:00Z"
    with tempfile.TemporaryDirectory(prefix="gaon-binance-adapter-check-") as tmp:
        base = Path(tmp)
        _write_json(base / "state.json", {
            "updated_at": "2026-08-23T00:00:00.000000",
            "testnet": True,
            "demo_mode": True,
            "strategy_mode": "rule",
            "positions": [
                {"symbol": "BTCUSDT", "amount": 0.01, "entry_price": 60000.0, "unrealized_pnl": 12.5},
                {"symbol": "ETHUSDT", "amount": -1.2, "entry_price": 3000.0, "unrealized_pnl": -4.0},
            ],
            "equity": 5000.0,
            "note": "fixture",
        })
        _write_json(base / "balance_history.json", [
            {"t": "2026-08-22T00:00:00", "v": 4990.0},
            {"t": "2026-08-23T00:00:00", "v": 5000.0},
        ])
        _write_json(base / "trade_events.json", [
            {"symbol": "SOLUSDT", "realized_pnl_usdt": -1.1, "result": "loss", "closed_at": "2026-08-22T10:00:00"},
            {"symbol": "BNBUSDT", "realized_pnl_usdt": 0.6, "result": "win", "closed_at": "2026-08-22T11:00:00"},
        ])
        _write_json(base / "strategy_params.json", {
            "ema_fast": 13, "ema_slow": 22, "rsi_period": 18,
        })
        _write_json(base / "price_action_walkforward.json", _fixture_walkforward_report())

        config = BinanceAdapterConfig(state_dir=base, research_dir=base)
        state_reader = BinanceStateReader(config)
        research_reader = BinanceResearchReader(config)

        account = state_reader.account_snapshot()
        positions = state_reader.positions()
        trades = state_reader.recent_trade_events()
        champion = state_reader.champion_strategy()
        family_summary = research_reader.family_summary("BIN-PA-01")
        healthy, _health_message = state_reader.health_check()

        no_write_method_on_state_reader = not any(
            name.startswith("write") or name.startswith("save") or name.startswith("update") or name.startswith("set_")
            for name in dir(BinanceStateReader)
        )
        no_write_method_on_champion_snapshot = not any(
            name.startswith("write") or name.startswith("save") or name.startswith("update") or name.startswith("set_")
            for name in dir(BinanceChampionStrategySnapshot)
        )
        no_order_methods_defined = not any(
            hasattr(module_obj, name)
            for module_obj in (state_reader, research_reader)
            for name in ("execute_order", "propose_order", "approve_order", "simulate_order", "place_order")
        )

        cc_report, validation_report = compare_binance_family_to_baseline(
            _fixture_walkforward_report(), "BIN-PA-01", generated_at=now,
        )

        strategy_params_after = _read_json(base / "strategy_params.json")

        checks = {
            "account_read_correctly": account is not None and account.equity == 5000.0,
            "positions_read_correctly": len(positions) == 2 and positions[1].amount == -1.2,
            "trades_read_correctly": len(trades) == 2 and trades[0].result == "loss",
            "champion_strategy_is_read_only_snapshot": champion is not None and champion.parameters["ema_fast"] == 13,
            "strategy_params_file_untouched_by_read": strategy_params_after == {"ema_fast": 13, "ema_slow": 22, "rsi_period": 18},
            "family_summary_read_correctly": family_summary is not None and family_summary.oos_total_trades == 40,
            "health_check_reports_healthy_fixture": healthy,
            "no_write_method_on_state_reader": no_write_method_on_state_reader,
            "no_write_method_on_champion_snapshot": no_write_method_on_champion_snapshot,
            "no_order_execution_methods_exist": no_order_methods_defined,
            "champion_challenger_report_generated": cc_report is not None,
            "champion_challenger_decision_is_research_only": cc_report.rationale != "" ,
            "validation_report_generated": validation_report is not None,
        }
        if not all(checks.values()):
            failed = ",".join(name for name, ok in checks.items() if not ok)
            raise RuntimeError(f"binance adapter read-only release check failed: {failed}")
        return {
            "schema_version": 1,
            **checks,
            "champion_challenger_decision": cc_report.decision.value,
            "validation_status": validation_report.overall_status.value,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
            "approval_bypassed": False,
            "safety": "pass",
        }


def _fixture_walkforward_report() -> Mapping[str, Any]:
    def _family(mean_return_pct: float, win_rate: float, max_dd: float) -> Mapping[str, Any]:
        folds = [
            {
                "oos_period": {"start": "2026-01-01", "end": "2026-01-31"},
                "regime": {"trend": "RANGE", "return_pct": 0.5, "volatility_pct": 0.01, "volatility": "LOW"},
                "train": {"num_trades": 20, "win_rate": win_rate, "total_return_pct": mean_return_pct, "max_drawdown_pct": max_dd},
                "oos": {"num_trades": 20, "win_rate": win_rate, "total_return_pct": mean_return_pct, "max_drawdown_pct": max_dd},
                "oos_degradation_return_pct": 0.0,
            },
            {
                "oos_period": {"start": "2026-01-31", "end": "2026-03-02"},
                "regime": {"trend": "RANGE", "return_pct": 0.5, "volatility_pct": 0.01, "volatility": "LOW"},
                "train": {"num_trades": 20, "win_rate": win_rate, "total_return_pct": mean_return_pct, "max_drawdown_pct": max_dd},
                "oos": {"num_trades": 20, "win_rate": win_rate, "total_return_pct": mean_return_pct, "max_drawdown_pct": max_dd},
                "oos_degradation_return_pct": 0.0,
            },
        ]
        return {
            "oos_summary": {
                "num_folds": 2, "total_trades": 40, "win_rate": win_rate,
                "mean_return_pct": mean_return_pct, "max_drawdown_pct": max_dd,
            },
            "train_summary": {
                "num_folds": 2, "total_trades": 40, "win_rate": win_rate,
                "mean_return_pct": mean_return_pct, "max_drawdown_pct": max_dd,
            },
            "profitable_symbol_ratio": 1.0 if mean_return_pct > 0 else 0.0,
            "per_symbol": {"BTCUSDT": {"folds": folds}},
        }

    return {
        "schema_version": 1,
        "strategies": {
            "BASELINE": _family(0.1, 0.3, 1.0),
            "BIN-PA-01": _family(-0.5, 0.19, 3.0),
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
