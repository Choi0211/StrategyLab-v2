from __future__ import annotations

import io
import unittest
import zipfile

from gaon.research.global_market import (
    KISMasterUniverseProvider,
    MarketScope,
    select_bounded_universe,
    yahoo_symbol_for,
)
from gaon.research.real_research import MarketSymbol


def zipped(name: str, payload: bytes) -> bytes:
    stream = io.BytesIO()

    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, payload)

    return stream.getvalue()


def domestic_record(
    symbol: str,
    isin: str,
    name: str,
    group: str,
    total_bytes: int,
) -> bytes:
    encoded_name = name.encode("cp949")

    if len(encoded_name) > 40:
        raise AssertionError(
            "fixture name exceeds KIS 40-byte field"
        )

    row = (
        symbol.ljust(9).encode("ascii")
        + isin.encode("ascii")
        + encoded_name
        + b" " * (40 - len(encoded_name))
        + group.encode("ascii")
    )

    return row + (
        b"0" * (total_bytes - len(row))
    )


class GlobalMarketProviderTests(unittest.TestCase):
    def test_us_master_stock_only(self) -> None:
        raw = (
            "US\t22\tNAS\tNASDAQ\tAAPL\tNASAAPL\t"
            "Apple\tApple Inc\t2\tUSD\n"
            "US\t22\tNAS\tNASDAQ\tQQQ\tNASQQQ\t"
            "QQQ\tETF\t3\tUSD\n"
        ).encode("cp949")

        provider = KISMasterUniverseProvider(
            fetcher=lambda url, timeout: zipped(
                "NASMST.COD",
                raw,
            )
        )

        scope = MarketScope(
            "US",
            ("NASDAQ",),
            ("USD",),
            ("America/New_York",),
            True,
            "US",
        )

        self.assertEqual(
            ("AAPL",),
            tuple(
                item.symbol
                for item in provider.fetch_universe(scope)
            ),
        )

    def test_us_master_skips_unsafe_special_identifier(
        self,
    ) -> None:
        raw = (
            "US\t21\tNYS\tNYSE\tIBM\tNYSIBM\t"
            "IBM\tInternational Business Machines\t2\tUSD\n"
            "US\t21\tNYS\tNYSE\t-BAD\tNYSBAD\t"
            "Bad\tBad Identifier\t2\tUSD\n"
            "US\t21\tNYS\tNYSE\tAAC/UN\tNYSAAC\t"
            "Unit\tAcquisition Unit\t2\tUSD\n"
        ).encode("cp949")

        provider = KISMasterUniverseProvider(
            fetcher=lambda url, timeout: zipped(
                "NYSMST.COD",
                raw,
            )
        )

        scope = MarketScope(
            "US",
            ("NYSE",),
            ("USD",),
            ("America/New_York",),
            True,
            "US",
        )

        self.assertEqual(
            ("IBM",),
            tuple(
                item.symbol
                for item in provider.fetch_universe(scope)
            ),
        )

    def test_domestic_master_byte_safe_common_stock(
        self,
    ) -> None:
        kospi_raw = b"\n".join(
            (
                domestic_record(
                    "005930",
                    "KR7005930003",
                    "\uc0bc\uc131\uc804\uc790",
                    "ST",
                    288,
                ),
                domestic_record(
                    "F70100",
                    "KR5701000303",
                    "\ud55c\ud22c\ud380\ub4dc",
                    "BC",
                    288,
                ),
            )
        )

        kosdaq_raw = b"\n".join(
            (
                domestic_record(
                    "247540",
                    "KR7247540008",
                    "\uc5d0\ucf54\ud504\ub85c\ube44\uc5e0",
                    "ST",
                    282,
                ),
                domestic_record(
                    "900110",
                    "HK0000057197",
                    "\ub531\ucee4\uba38\uc2a4",
                    "FS",
                    282,
                ),
            )
        )

        payloads = {
            "kospi_code.mst.zip": zipped(
                "kospi_code.mst",
                kospi_raw,
            ),
            "kosdaq_code.mst.zip": zipped(
                "kosdaq_code.mst",
                kosdaq_raw,
            ),
        }

        def fetcher(
            url: str,
            timeout: float,
        ) -> bytes:
            del timeout

            for name, payload in payloads.items():
                if url.endswith(name):
                    return payload

            raise AssertionError(
                f"unexpected URL: {url}"
            )

        provider = KISMasterUniverseProvider(
            fetcher=fetcher,
        )

        kospi_scope = MarketScope(
            "KR",
            ("KOSPI",),
            ("KRW",),
            ("Asia/Seoul",),
            True,
            "KR",
        )

        kosdaq_scope = MarketScope(
            "KR",
            ("KOSDAQ",),
            ("KRW",),
            ("Asia/Seoul",),
            True,
            "KR",
        )

        kospi = provider.fetch_universe(
            kospi_scope
        )
        kosdaq = provider.fetch_universe(
            kosdaq_scope
        )

        self.assertEqual(
            ("005930",),
            tuple(x.symbol for x in kospi),
        )
        self.assertEqual(
            "\uc0bc\uc131\uc804\uc790",
            kospi[0].name,
        )

        self.assertEqual(
            ("247540",),
            tuple(x.symbol for x in kosdaq),
        )
        self.assertEqual(
            "\uc5d0\ucf54\ud504\ub85c\ube44\uc5e0",
            kosdaq[0].name,
        )

    def test_bounded_breadth(self) -> None:
        rows = (
            MarketSymbol(
                "AAPL",
                "A",
                "US",
                "NASDAQ",
            ),
            MarketSymbol(
                "MSFT",
                "M",
                "US",
                "NASDAQ",
            ),
            MarketSymbol(
                "IBM",
                "I",
                "US",
                "NYSE",
            ),
            MarketSymbol(
                "BMY",
                "B",
                "US",
                "NYSE",
            ),
            MarketSymbol(
                "ABC",
                "C",
                "US",
                "AMEX",
            ),
        )

        scope = MarketScope(
            "US",
            (
                "NASDAQ",
                "NYSE",
                "AMEX",
            ),
            ("USD",),
            ("America/New_York",),
            True,
            "US",
        )

        selection = select_bounded_universe(
            rows,
            scope,
            requested_size=3,
            seed="unit",
            source="unit",
        )

        self.assertEqual(
            5,
            selection.candidate_count,
        )

        selected_exchanges = {
            row.exchange
            for row in rows
            if row.symbol in selection.symbols
        }

        self.assertEqual(
            {
                "NASDAQ",
                "NYSE",
                "AMEX",
            },
            selected_exchanges,
        )

    def test_yahoo_mapping(self) -> None:
        self.assertEqual(
            "005930.KS",
            yahoo_symbol_for(
                MarketSymbol(
                    "005930",
                    "S",
                    "KR",
                    "KOSPI",
                )
            ),
        )

        self.assertEqual(
            "091990.KQ",
            yahoo_symbol_for(
                MarketSymbol(
                    "091990",
                    "X",
                    "KR",
                    "KOSDAQ",
                )
            ),
        )

        self.assertEqual(
            "AAPL",
            yahoo_symbol_for(
                MarketSymbol(
                    "AAPL",
                    "A",
                    "US",
                    "NASDAQ",
                )
            ),
        )

        self.assertEqual(
            "BRK-B",
            yahoo_symbol_for(
                MarketSymbol(
                    "BRK.B",
                    "B",
                    "US",
                    "NYSE",
                )
            ),
        )

        self.assertEqual(
            "7203.T",
            yahoo_symbol_for(
                MarketSymbol(
                    "7203",
                    "T",
                    "JP",
                    "TSE",
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
