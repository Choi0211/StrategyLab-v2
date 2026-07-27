import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


class TimezoneDependencyTests(unittest.TestCase):
    def test_asia_seoul_zoneinfo_is_available(self) -> None:
        zone = ZoneInfo("Asia/Seoul")
        self.assertEqual(zone.key, "Asia/Seoul")
        self.assertEqual(datetime(2026, 1, 1, tzinfo=zone).utcoffset().total_seconds(), 9 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
