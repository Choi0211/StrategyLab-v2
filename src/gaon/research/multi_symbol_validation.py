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
from typing import Iterable, Mapping

from gaon.research.real_research import MarketDataset, MarketSymbol

_WARMUP_BARS = 60
_TRAIN_FRACTION = 0.65
_MIN_TRAIN_BARS = 70

# The robustness path already refuses to run on fewer than 140 primary
# bars; a relative-strength candidate must have at least that many bars
# that the primary AND every peer actually share.
_MIN_ALIGNED_BARS = 140
_PEER_TIMELINE_COVERAGE_FLOOR = 0.9


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


def build_relative_strength_validation_dataset(
    primary_dataset: MarketDataset,
    peer_datasets: "Iterable[MarketDataset] | Mapping[str, MarketDataset]",
    *,
    primary_symbol: str,
    min_aligned_bars: int = _MIN_ALIGNED_BARS,
) -> MarketDataset:
    """Combine a single-symbol primary dataset with one or more REAL peer
    datasets into one multi-symbol ``MarketDataset`` restricted to the
    closed-bar timestamps the primary and EVERY peer actually share.

    Fails closed (``MultiSymbolValidationError``) - never fabricates a
    peer, a benchmark, or a bar - when:

    * the primary symbol has no bars in the primary dataset,
    * there is no peer symbol distinct from the primary,
    * fewer than ``min_aligned_bars`` bars are shared by the primary and
      every peer (peer history insufficient / alignment impossible),
    * the shared grid covers under 90% of the primary's own timeline
      (a peer does not span the validation window),
    * (final guard) ``MultiSymbolValidationContext.from_dataset`` rejects
      the combined result.
    """
    if isinstance(peer_datasets, Mapping):
        peer_list = list(peer_datasets.values())
    else:
        peer_list = list(peer_datasets)

    primary_bars = [b for b in primary_dataset.bars if b.symbol == primary_symbol]
    if not primary_bars:
        raise MultiSymbolValidationError(
            f"primary symbol {primary_symbol!r} has no bars in the primary dataset"
        )
    if not peer_list:
        raise MultiSymbolValidationError(
            "relative-strength validation needs at least one real peer dataset"
        )

    primary_ts = sorted({b.timestamp for b in primary_bars})

    peer_bars_by_symbol: dict[str, list] = {}
    for peer_dataset in peer_list:
        for bar in peer_dataset.bars:
            if bar.symbol == primary_symbol:
                continue
            peer_bars_by_symbol.setdefault(bar.symbol, []).append(bar)
    if not peer_bars_by_symbol:
        raise MultiSymbolValidationError(
            "no peer symbol distinct from the primary in the supplied peer datasets"
        )

    common_ts = set(primary_ts)
    for bars in peer_bars_by_symbol.values():
        common_ts &= {b.timestamp for b in bars}
    common_sorted = sorted(common_ts)

    if len(common_sorted) < min_aligned_bars:
        raise MultiSymbolValidationError(
            f"only {len(common_sorted)} closed bars are shared by the primary and every peer "
            f"(need >= {min_aligned_bars}); no forward-fill / fabrication"
        )
    if len(common_sorted) < int(len(primary_ts) * _PEER_TIMELINE_COVERAGE_FLOOR):
        raise MultiSymbolValidationError(
            f"the shared timestamp grid ({len(common_sorted)}) covers under "
            f"{int(_PEER_TIMELINE_COVERAGE_FLOOR * 100)}% of the primary timeline "
            f"({len(primary_ts)}) - a peer does not span the validation window; fail closed"
        )

    common_set = set(common_sorted)
    dedup: dict[tuple[str, str], object] = {}
    for bar in primary_bars:
        if bar.timestamp in common_set:
            dedup[(bar.symbol, bar.timestamp)] = bar
    for symbol, bars in peer_bars_by_symbol.items():
        for bar in bars:
            if bar.timestamp in common_set:
                dedup.setdefault((symbol, bar.timestamp), bar)

    combined_bars = tuple(sorted(dedup.values(), key=lambda b: (b.timestamp, b.symbol)))
    market = primary_dataset.metadata.market
    symbols = tuple(
        MarketSymbol(s, s, market)
        for s in [primary_symbol, *sorted(peer_bars_by_symbol)]
    )
    metadata = replace(
        primary_dataset.metadata,
        start_date=common_sorted[0],
        end_date=common_sorted[-1],
    )
    combined = MarketDataset(
        f"{primary_dataset.dataset_id}:rs-multi-symbol",
        symbols,
        combined_bars,
        metadata,
        getattr(primary_dataset, "corporate_actions", ()),
    )
    # final fail-closed assertion - never return a dataset the existing
    # context check would reject.
    MultiSymbolValidationContext.from_dataset(combined, primary_symbol=primary_symbol)
    return combined


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
