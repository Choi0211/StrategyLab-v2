"""Market data validation for StrategyLab v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from strategylab.market.models import MarketBar, MarketDataset


@dataclass(frozen=True)
class ValidationIssue:
    """Single validation issue."""

    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of market data validation."""

    passed: bool
    issues: tuple[ValidationIssue, ...] = ()

    @classmethod
    def pass_result(cls) -> "ValidationResult":
        return cls(passed=True)

    @classmethod
    def fail(cls, issues: list[ValidationIssue]) -> "ValidationResult":
        return cls(passed=False, issues=tuple(issues))


class MarketDataValidator:
    """Validate market datasets before they are used by research workflows."""

    def validate(
        self,
        dataset: MarketDataset,
        expected_symbols: tuple[str, ...] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []

        if not dataset.bars:
            issues.append(ValidationIssue("empty_dataset", "dataset has no bars"))

        self._validate_bars(dataset.bars, issues)
        self._validate_duplicate_timestamps(dataset.bars, issues)
        self._validate_symbol_universe(dataset, expected_symbols, issues)
        self._validate_date_range(dataset, start, end, issues)

        if issues:
            return ValidationResult.fail(issues)
        return ValidationResult.pass_result()

    def _validate_bars(self, bars: tuple[MarketBar, ...], issues: list[ValidationIssue]) -> None:
        for index, bar in enumerate(bars):
            for field_name in ("symbol", "timestamp", "open", "high", "low", "close", "volume"):
                if getattr(bar, field_name) is None:
                    issues.append(
                        ValidationIssue(
                            "missing_value",
                            f"bar {index} has missing {field_name}",
                        )
                    )
            if bar.high < bar.low:
                issues.append(ValidationIssue("invalid_ohlc", f"bar {index} high is lower than low"))
            if bar.volume < 0:
                issues.append(ValidationIssue("invalid_volume", f"bar {index} volume is negative"))

    def _validate_duplicate_timestamps(
        self,
        bars: tuple[MarketBar, ...],
        issues: list[ValidationIssue],
    ) -> None:
        seen: set[tuple[str, object]] = set()
        for bar in bars:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                issues.append(
                    ValidationIssue(
                        "duplicate_timestamp",
                        f"duplicate timestamp for {bar.symbol} at {bar.timestamp.isoformat()}",
                    )
                )
            seen.add(key)

    def _validate_symbol_universe(
        self,
        dataset: MarketDataset,
        expected_symbols: tuple[str, ...] | None,
        issues: list[ValidationIssue],
    ) -> None:
        if expected_symbols is None:
            return
        if tuple(sorted(expected_symbols)) != dataset.symbols:
            issues.append(
                ValidationIssue(
                    "symbol_universe_mismatch",
                    f"expected {tuple(sorted(expected_symbols))}, got {dataset.symbols}",
                )
            )

    def _validate_date_range(
        self,
        dataset: MarketDataset,
        start: date | None,
        end: date | None,
        issues: list[ValidationIssue],
    ) -> None:
        if not dataset.bars:
            return
        if start is not None and dataset.start_date is not None and dataset.start_date < start:
            issues.append(ValidationIssue("date_range_mismatch", "dataset starts before requested range"))
        if end is not None and dataset.end_date is not None and dataset.end_date > end:
            issues.append(ValidationIssue("date_range_mismatch", "dataset ends after requested range"))

