from __future__ import annotations

import unittest

from gaon.research.global_market import (
    resolve_market_scope,
)
from gaon.runtime.llm_conversation import (
    _default_tool_arguments,
)
from gaon.runtime.llm_tool_routing import (
    route_read_only_tool,
)


class GlobalMarketProductionRoutingTests(
    unittest.TestCase
):
    def test_us_multiple_exchanges_are_preserved(
        self,
    ) -> None:
        text = (
            "\uac00\uc628\uc544 "
            "\ubbf8\uad6d \uc8fc\uc2dd "
            "\uc804\uccb4\ub97c "
            "\ub300\uc0c1\uc73c\ub85c "
            "\uc5f0\uad6c\ud574 \uc8fc\uc138\uc694. "
            "\ub098\uc2a4\ub2e5, NYSE, AMEX\ub97c "
            "\uae30\uc900\uc73c\ub85c "
            "\uc2e4\uc81c \uc2dc\uc7a5 "
            "\ub370\uc774\ud130\ub97c "
            "\uc0ac\uc6a9\ud574\uc11c "
            "\uc5f0\uad6c\ud574\uc8fc\uc138\uc694."
        )

        scope = resolve_market_scope(text)

        self.assertIsNotNone(scope)
        self.assertEqual(
            "US",
            scope.market,
        )
        self.assertEqual(
            (
                "NASDAQ",
                "NYSE",
                "AMEX",
            ),
            scope.exchanges,
        )

        self.assertEqual(
            "multi_symbol_research",
            route_read_only_tool(text),
        )

        args = _default_tool_arguments(
            "multi_symbol_research",
            text,
        )

        self.assertEqual(
            (),
            args["symbols"],
        )
        self.assertEqual(
            "curated",
            args["universe_type"],
        )

    def test_nasdaq_only_remains_nasdaq(
        self,
    ) -> None:
        text = (
            "\uac00\uc628\uc544 "
            "\ub098\uc2a4\ub2e5 "
            "\uc804\uccb4\ub97c "
            "\ub300\uc0c1\uc73c\ub85c "
            "\uc5f0\uad6c\ud574\uc8fc\uc138\uc694."
        )

        scope = resolve_market_scope(text)

        self.assertIsNotNone(scope)
        self.assertEqual(
            "US",
            scope.market,
        )
        self.assertEqual(
            ("NASDAQ",),
            scope.exchanges,
        )

    def test_kr_us_compare_routes_to_multi(
        self,
    ) -> None:
        text = (
            "\uac00\uc628\uc544 "
            "\ud55c\uad6d\uacfc \ubbf8\uad6d "
            "\uc8fc\uc2dd \uc804\uccb4\ub97c "
            "\ub300\uc0c1\uc73c\ub85c "
            "\ube44\uad50 \uc5f0\uad6c\ud574\uc8fc\uc138\uc694. "
            "\ucf54\uc2a4\ud53c, "
            "\ucf54\uc2a4\ub2e5, "
            "\ub098\uc2a4\ub2e5, "
            "NYSE, AMEX\ub97c "
            "\ud3ec\ud568\ud558\uace0 "
            "\uc2e4\uc81c \uc2dc\uc7a5 "
            "\ub370\uc774\ud130\ub97c "
            "\uc0ac\uc6a9\ud574\uc8fc\uc138\uc694."
        )

        scope = resolve_market_scope(text)

        self.assertIsNotNone(scope)
        self.assertEqual(
            "MULTI",
            scope.market,
        )
        self.assertEqual(
            (
                "KOSPI",
                "KOSDAQ",
                "NASDAQ",
                "NYSE",
                "AMEX",
            ),
            scope.exchanges,
        )

        self.assertEqual(
            "multi_symbol_research",
            route_read_only_tool(text),
        )

        args = _default_tool_arguments(
            "multi_symbol_research",
            text,
        )

        self.assertEqual(
            (),
            args["symbols"],
        )
        self.assertEqual(
            "curated",
            args["universe_type"],
        )

    def test_aapl_explicit_routes_to_multi_symbol(
        self,
    ) -> None:
        text = (
            "\uac00\uc628\uc544 "
            "\ubbf8\uad6d\uc8fc\uc2dd AAPL "
            "\uc804\ub7b5\uc744 "
            "\uc5f0\uad6c\ud574\uc8fc\uc138\uc694. "
            "\uc2e4\uc81c \uc2dc\uc7a5 "
            "\ub370\uc774\ud130\ub97c "
            "\uc0ac\uc6a9\ud574\uc11c "
            "\uac80\uc99d\ud574\uc8fc\uc138\uc694."
        )

        scope = resolve_market_scope(text)

        self.assertIsNotNone(scope)
        self.assertEqual(
            "US",
            scope.market,
        )

        self.assertEqual(
            "multi_symbol_research",
            route_read_only_tool(text),
        )

        args = _default_tool_arguments(
            "multi_symbol_research",
            text,
        )

        self.assertEqual(
            ("AAPL",),
            args["symbols"],
        )
        self.assertEqual(
            "explicit",
            args["universe_type"],
        )


if __name__ == "__main__":
    unittest.main()
