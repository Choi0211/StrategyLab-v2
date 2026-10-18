import unittest
from datetime import datetime,timezone
from gaon.research.closed_bar_validation import validate_closed_bars

def candles():
    return [{"timestamp":f"2026-10-18T10:{i:02}:00Z"} for i in range(3)]

class ClosedBarValidationTests(unittest.TestCase):
    def test_valid_closed_bars(self):
        self.assertTrue(validate_closed_bars(candles(),as_of=datetime(2026,10,18,10,3,tzinfo=timezone.utc),timeframe_seconds=60))

    def test_open_bar_rejected(self):
        with self.assertRaisesRegex(ValueError,"unclosed"):
            validate_closed_bars(candles(),as_of=datetime(2026,10,18,10,2,30,tzinfo=timezone.utc),timeframe_seconds=60)

    def test_bad_timestamps(self):
        mutations=[
            lambda b: b[1].update(timestamp=b[0]["timestamp"]),
            lambda b: b[1].update(timestamp="2026-10-18T09:00:00Z"),
            lambda b: b[1].update(timestamp="2026-10-18T10:01:00"),
            lambda b: b[1].update(timestamp="not-a-date"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                b=candles();mutate(b)
                with self.assertRaises(ValueError): validate_closed_bars(b)

if __name__=="__main__": unittest.main()
