import io
import json
import unittest
from contextlib import redirect_stdout

from gaon.runtime.cli import main as cli_main


class KRXUniverseFlowTests(unittest.TestCase):
    def test_cli_json_output_and_release_check(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(
                cli_main(["krx-universe-select", "--market", "ALL", "--date", "2026-07-30", "--metric", "trading_value", "--size", "3", "--json"]),
                0,
            )
        payload = json.loads(buffer.getvalue())

        self.assertEqual(payload["selected_size"], 3)
        self.assertEqual(payload["request"]["ranking_metric"], "trading_value")
        self.assertTrue(payload["fixture_backed"])
        self.assertEqual(payload["symbols"], ["005930", "000660", "005380"])

        self.assertEqual(cli_main(["krx-universe-release-check"]), 0)

    def test_existing_explicit_multi_symbol_release_check_still_passes(self) -> None:
        self.assertEqual(cli_main(["multi-symbol-research-release-check", "--db", ":memory:"]), 0)


if __name__ == "__main__":
    unittest.main()
