import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from gaon.research.offline_research_cli import main
from gaon.learning.experience_journal import summary

class OfflineResearchCliTests(unittest.TestCase):
    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            candles=[dict(symbol="BTCUSDT",timestamp=f"2026-01-01T{i//60:02}:{i%60:02}:00Z",
              open=100+i*.3,high=102+i*.3,low=99+i*.3,
              close=101+i*.3,volume=1000+i*10) for i in range(80)]
            path=tmp_path/"bars.json"
            path.write_text(json.dumps(candles),encoding="utf-8")
            db=tmp_path/"journal.sqlite"
            args=["--input",str(path),"--database",str(db),"--market","BINANCE",
                  "--account","research","--strategy-version-id","candidate-v1","--timeframe","1m"]
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(args),0)
            first=json.loads(out.getvalue())
            self.assertTrue(first["journal_inserted"])
            self.assertFalse(first["eligible_for_promotion"])
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(args),0)
            second=json.loads(out.getvalue())
            self.assertFalse(second["journal_inserted"])
            self.assertEqual(first["run_id"],second["run_id"])
            with sqlite3.connect(db) as connection:
                x=summary(connection,market="BINANCE",account="research",strategy_version_id="candidate-v1")
                self.assertEqual(x["experiments"],1)
                self.assertEqual(x["trades"],0)

    def test_cli_rejects_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            path=tmp_path/"bad.json"
            path.write_text('{"bad":true}',encoding="utf-8")
            db=tmp_path/"journal.sqlite"
            with self.assertRaises(SystemExit) as exc:
                main(["--input",str(path),"--database",str(db),"--market","BINANCE",
                      "--account","research","--strategy-version-id","v1","--timeframe","1m"])
            self.assertEqual(exc.exception.code,2)
            self.assertFalse(db.exists())

if __name__=="__main__": unittest.main()
