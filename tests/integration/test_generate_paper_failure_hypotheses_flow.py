"""End-to-end test of scripts/generate_paper_failure_hypotheses.py against a
TEMP, isolated sqlite file - never the production DB. Verifies: real
closed-trade data drives hypothesis generation automatically, results are
persisted (structured table + companion research memory), and re-running
is idempotent.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from gaon.research.self_improving import SQLiteResearchMemoryRepository
from gaon.runtime.migrations import migrate
from gaon.runtime.paper_failure_hypothesis_repository import PaperFailureHypothesisSQLiteRepository
from gaon.runtime.paper_observation_repository import PaperObservationSQLiteRepository

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_paper_failure_hypotheses.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("generate_paper_failure_hypotheses", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAMILY_ID = "csm-48h-long"


def _closed_obs(symbol: str, pnl: float, fees: float = -0.1, reason: str = "48h_timed_exit", n: int = 1):
    return [
        {
            "family_id": FAMILY_ID, "strategy_version_id": "strategy-version:test", "spec_fingerprint": "fp-test",
            "direction": "LONG", "symbol": symbol, "status": "closed",
            "signal_at": "2026-10-20T00:00:00Z", "entry_at": "2026-10-20T00:00:00Z", "exit_at": "2026-10-22T00:00:00Z",
            "entry_price": 1.0, "exit_price": 1.0 + pnl / 100.0, "qty": 100.0,
            "pnl": pnl, "pnl_pct": pnl / 100.0, "fees": fees, "reason": reason,
        }
        for _ in range(n)
    ]


class GeneratePaperFailureHypothesesFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite", prefix="test_paper_failure_hypotheses_")
        os.close(fd)
        os.remove(self.db_path)  # created fresh by sqlite3.connect/migrate below
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.remove(self.db_path))
        connection = sqlite3.connect(self.db_path)
        migrate(connection)
        connection.close()
        self.module = _load_script_module()

    def _seed_observations(self, observations: list[dict]) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            repo = PaperObservationSQLiteRepository(connection)
            for i, obs in enumerate(observations):
                # Each trade needs a distinct entry_at/exit_at to avoid colliding
                # with the (family_id, symbol, status, entry_at, exit_at) unique
                # index - vary a seconds offset per seeded row.
                obs = dict(obs, entry_at=f"2026-10-20T00:00:{i:02d}+00:00", exit_at=f"2026-10-22T00:00:{i:02d}+00:00")
                repo.insert(obs, created_at=obs["exit_at"])
        finally:
            connection.close()

    def test_no_closed_trades_yet_generates_insufficient_data_hypothesis(self) -> None:
        exit_code = self.module.run(self.db_path, FAMILY_ID)
        self.assertEqual(exit_code, 0)
        connection = sqlite3.connect(self.db_path)
        try:
            hyp_repo = PaperFailureHypothesisSQLiteRepository(connection)
            rows = hyp_repo.list_for_family(FAMILY_ID)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pattern_type"], "insufficient_data")
            self.assertEqual(rows[0]["status"], "insufficient_evidence")
            self.assertIsNone(rows[0]["confidence"])
        finally:
            connection.close()

    def test_real_closed_trades_drive_automatic_hypothesis_generation(self) -> None:
        """This is the acceptance check for 'does analysis run automatically
        when real closed trades exist' - seeded data here plays the role of
        what the Paper engine would have reported, but is seeded directly
        into this TEMP db, never the production one."""
        observations = _closed_obs("QNTUSDT", pnl=100.0, n=1) + _closed_obs("OTHERUSDT", pnl=5.0, n=9)
        self._seed_observations(observations)

        exit_code = self.module.run(self.db_path, FAMILY_ID)
        self.assertEqual(exit_code, 0)

        connection = sqlite3.connect(self.db_path)
        try:
            hyp_repo = PaperFailureHypothesisSQLiteRepository(connection)
            rows = hyp_repo.list_for_family(FAMILY_ID)
            patterns = {r["pattern_type"] for r in rows}
            self.assertIn("symbol_concentration", patterns)
            concentration = next(r for r in rows if r["pattern_type"] == "symbol_concentration")
            self.assertEqual(concentration["status"], "candidate")
            self.assertEqual(concentration["evidence"]["top_symbol"], "QNTUSDT")

            memory_repo = SQLiteResearchMemoryRepository(connection)
            memories = memory_repo.search(tag=FAMILY_ID)
            self.assertEqual(len(memories), 1)
            self.assertIn("QNTUSDT", memories[0].result_summary)
        finally:
            connection.close()

    def test_rerunning_on_unchanged_data_is_idempotent(self) -> None:
        observations = _closed_obs("QNTUSDT", pnl=100.0, n=1) + _closed_obs("OTHERUSDT", pnl=5.0, n=9)
        self._seed_observations(observations)

        self.module.run(self.db_path, FAMILY_ID)
        connection = sqlite3.connect(self.db_path)
        hyp_count_after_first = len(PaperFailureHypothesisSQLiteRepository(connection).list_for_family(FAMILY_ID))
        memory_count_after_first = len(SQLiteResearchMemoryRepository(connection).search(tag=FAMILY_ID))
        connection.close()

        self.module.run(self.db_path, FAMILY_ID)
        connection = sqlite3.connect(self.db_path)
        try:
            hyp_count_after_second = len(PaperFailureHypothesisSQLiteRepository(connection).list_for_family(FAMILY_ID))
            memory_count_after_second = len(SQLiteResearchMemoryRepository(connection).search(tag=FAMILY_ID))
            self.assertEqual(hyp_count_after_first, hyp_count_after_second)
            self.assertEqual(memory_count_after_first, memory_count_after_second)
        finally:
            connection.close()

    def test_new_closed_trade_after_a_run_produces_a_new_memory_not_a_duplicate_of_the_old_one(self) -> None:
        observations = _closed_obs("QNTUSDT", pnl=100.0, n=1) + _closed_obs("OTHERUSDT", pnl=5.0, n=9)
        self._seed_observations(observations)
        self.module.run(self.db_path, FAMILY_ID)

        # A genuinely new closed trade arrives - the evidence changes, so a
        # new memory (and possibly new/updated hypotheses) should follow.
        connection = sqlite3.connect(self.db_path)
        repo = PaperObservationSQLiteRepository(connection)
        new_obs = _closed_obs("OTHERUSDT", pnl=-200.0, n=1)[0]
        repo.insert(dict(new_obs, entry_at="2026-10-21T00:00:00+00:00", exit_at="2026-10-23T00:00:00+00:00"), created_at="t")
        connection.close()

        self.module.run(self.db_path, FAMILY_ID)
        connection = sqlite3.connect(self.db_path)
        try:
            memories = SQLiteResearchMemoryRepository(connection).search(tag=FAMILY_ID)
            self.assertEqual(len(memories), 2, "a changed aggregate must produce a second, distinct memory")
        finally:
            connection.close()

    def test_never_touches_strategy_version_registries(self) -> None:
        observations = _closed_obs("QNTUSDT", pnl=100.0, n=1) + _closed_obs("OTHERUSDT", pnl=5.0, n=9)
        self._seed_observations(observations)
        self.module.run(self.db_path, FAMILY_ID)
        connection = sqlite3.connect(self.db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM strategy_version_registries").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
