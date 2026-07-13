from datetime import date, datetime

from strategylab.market import DataProvenance, DataSourceMetadata, MarketBar, MarketDataset


def sample_provenance() -> DataProvenance:
    return DataProvenance(
        source=DataSourceMetadata(
            source_name="synthetic-fixture",
            collected_at=datetime(2026, 7, 14, 9, 0, 0),
            frequency="1d",
            timezone="Asia/Seoul",
        ),
        symbol_universe=("AAA", "BBB"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        preprocessing_steps=("synthetic fixture",),
    )


def sample_dataset() -> MarketDataset:
    return MarketDataset(
        bars=(
            MarketBar("AAA", datetime(2026, 1, 1), 100.0, 110.0, 95.0, 105.0, 1000.0),
            MarketBar("AAA", datetime(2026, 1, 2), 105.0, 112.0, 100.0, 111.0, 1200.0),
            MarketBar("BBB", datetime(2026, 1, 1), 50.0, 55.0, 48.0, 54.0, 900.0),
            MarketBar("BBB", datetime(2026, 1, 3), 54.0, 60.0, 52.0, 58.0, 1100.0),
        ),
        provenance=sample_provenance(),
    )

