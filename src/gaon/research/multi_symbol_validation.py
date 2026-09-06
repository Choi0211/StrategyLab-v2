"""Priority 4 - a REAL multi-symbol validation context.

``RuleBasedBacktestEngine.run`` already accepts a multi-symbol
``MarketDataset`` (PR #190). The gap this closes is the walk-forward /
robustness split: it used a mixed-symbol BAR INDEX, which for a
multi-symbol dataset would cut the peer group at an arbitrary point.

``walk_forward_timestamp_split`` instead cuts every symbol at the SAME
TIMESTAMP, derived from the PRIMARY symbol's own timeline. For a
single-symbol dataset it is identical, bar for bar, to the historical
index split.

``MultiSymbolValidationContext.from_dataset`` fails CLOSED - it raises
rather than proceed with a partial or invented peer set - when: the
primary symbol is absent, there is no peer, or a peer does not cover the
full primary timeline (closed bars only, exact timestamp alignment; no
backfill, no interpolation, no synthetic peer).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from gaon.research.real_research import MarketDataset

_WARMUP_BARS = 60
_TRAIN_FRACTION = 0.65
_MIN_TRAIN_BARS = 70


class MultiSymbolValidationError(ValueError):
    """A dataset cannot back a real multi-symbol (relative-strength)
    validation. Fail closed."""


@dataclass(frozen=True)
class MultiSymbolValidationContext:
    primary_symbol: str
    peer_symbols: tuple[str, ...]
    primary_timestamps: tuple[str, ...]

    @classmethod
    def from_dataset(cls, dataset: MarketDataset, *, primary_symbol: str) -> "MultiSymbolValidationContext":
        by_symbol: dict[str, set[str]] = {}
        for bar in dataset.bars:
            by_symbol.setdefault(bar.symbol, set()).add(bar.timestamp)

        if primary_symbol not in by_symbol:
            raise MultiSymbolValidationError(f"primary symbol {primary_symbol!r} is absent from the dataset")

        peers = tuple(sorted(s for s in by_symbol if s != primary_symbol))
        if not peers:
            raise MultiSymbolValidationError("relative-strength validation needs at least one real peer symbol")

        primary_ts = tuple(sorted(by_symbol[primary_symbol]))
        primary_ts_set = set(primary_ts)
        for peer in peers:
            missing = primary_ts_set - by_symbol[peer]
            if missing:
                raise MultiSymbolValidationError(
                    f"peer {peer!r} does not cover {len(missing)} of the primary's {len(primary_ts)} bars "
                    f"- no backfill / interpolation; fail closed"
                )
        return cls(primary_symbol, peers, primary_ts)


def walk_forward_timestamp_split(
    dataset: MarketDataset, *, primary_symbol: str
) -> tuple[MarketDataset, MarketDataset]:
    """(train, test) split at a single timestamp on the primary symbol's
    timeline. Every symbol's bars are cut at the same date; the test
    window overlaps the train window by ``_WARMUP_BARS`` primary bars."""
    all_bars = sorted(dataset.bars, key=lambda b: b.timestamp)
    primary_ts = sorted({b.timestamp for b in all_bars if b.symbol == primary_symbol})
    if not primary_ts:
        # historical single-symbol call where bar.symbol may differ from
        # strategy.symbol - fall back to the whole timeline (unchanged).
        primary_ts = sorted({b.timestamp for b in all_bars})

    n = len(primary_ts)
    split_index = min(n, max(_MIN_TRAIN_BARS, int(n * _TRAIN_FRACTION)))
    train_cutoff_ts = primary_ts[max(0, split_index - 1)]
    test_start_ts = primary_ts[max(0, split_index - _WARMUP_BARS)]

    train = replace(
        dataset,
        dataset_id=f"{dataset.dataset_id}:train",
        bars=tuple(b for b in all_bars if b.timestamp <= train_cutoff_ts),
    )
    test = replace(
        dataset,
        dataset_id=f"{dataset.dataset_id}:test",
        bars=tuple(b for b in all_bars if b.timestamp >= test_start_ts),
    )
    return train, test
