from __future__ import annotations

import unittest

from gaon.research.global_market import (
    extract_market_symbols,
    is_market_universe_request,
    resolve_market_scope,
)
from gaon.runtime.llm_conversation import (
    _default_tool_arguments,
)
from gaon.runtime.llm_tool_routing import (
    route_read_only_tool,
)


class GlobalMarketScopeTests(unittest.TestCase):
    def test_whole_market_common_route(self) -> None:
        cases = (
            (
                "\ud55c\uad6d \uc8fc\uc2dd "
                "\uc804\uccb4\ub97c \uc5f0\uad6c\ud574\uc918",
                "KR",
            ),
            (
                "\ubbf8\uad6d \uc8fc\uc2dd "
                "\uc804\uccb4\ub97c \uc5f0\uad6c\ud574\uc918",
                "US",
            ),
            (
                "\ub098\uc2a4\ub2e5 \uc804\uccb4\ub97c "
                "\uc5f0\uad6c\ud574\uc918",
                "US",
            ),
            (
                "\ud55c\uad6d\uacfc \ubbf8\uad6d \uc8fc\uc2dd "
                "\uc804\uccb4\ub97c \ube44\uad50 "
                "\uc5f0\uad6c\ud574\uc918",
                "MULTI",
            ),
        )

        for text, expected_market in cases:
            scope = resolve_market_scope(text)

            self.assertIsNotNone(scope)
            assert scope is not None

            self.assertEqual(
                expected_market,
                scope.market,
            )
            self.assertTrue(
                is_market_universe_request(text)
            )
            self.assertEqual(
                "multi_symbol_research",
                route_read_only_tool(text),
            )

            arguments = _default_tool_arguments(
                "multi_symbol_research",
                text,
            )

            self.assertEqual(
                (),
                arguments["symbols"],
            )
            self.assertEqual(
                "curated",
                arguments["universe_type"],
            )

    def test_us_explicit_ticker(self) -> None:
        text = (
            "\ubbf8\uad6d\uc8fc\uc2dd AAPL "
            "\uc804\ub7b5\uc744 \uc5f0\uad6c\ud574\uc918"
        )

        scope = resolve_market_scope(text)

        self.assertIsNotNone(scope)
        assert scope is not None

        self.assertFalse(scope.universe_requested)

        self.assertEqual(
            ("AAPL",),
            extract_market_symbols(text, scope),
        )

        self.assertEqual(
            "multi_symbol_research",
            route_read_only_tool(text),
        )

        arguments = _default_tool_arguments(
            "multi_symbol_research",
            text,
        )

        self.assertEqual(
            ("AAPL",),
            arguments["symbols"],
        )

    def test_future_market_metadata(self) -> None:
        cases = (
            (
                "\uc77c\ubcf8 \uc8fc\uc2dd \uc804\uccb4",
                "JP",
                "JPY",
                "Asia/Tokyo",
            ),
            (
                "\ud64d\ucf69 \uc8fc\uc2dd \uc804\uccb4",
                "HK",
                "HKD",
                "Asia/Hong_Kong",
            ),
            (
                "\uc911\uad6d \uc8fc\uc2dd \uc804\uccb4",
                "CN",
                "CNY",
                "Asia/Shanghai",
            ),
        )

        for text, market, currency, timezone in cases:
            scope = resolve_market_scope(text)

            self.assertIsNotNone(scope)
            assert scope is not None

            self.assertEqual(market, scope.market)
            self.assertEqual(
                currency,
                scope.primary_currency,
            )
            self.assertEqual(
                timezone,
                scope.primary_timezone,
            )


if __name__ == "__main__":
    unittest.main()
