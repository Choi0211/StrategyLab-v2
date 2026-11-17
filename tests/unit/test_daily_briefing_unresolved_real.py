import sqlite3
import unittest
from types import SimpleNamespace

from gaon.runtime import daily_briefing as d


def _record(symbol: str, action: str, reason: str, terminal: bool = False, audit_id: str = "a"):
    return SimpleNamespace(
        audit_id=f"{audit_id}-{symbol}",
        result={"output": {"symbol": symbol, "autonomous_learning_v2": {
            "research_director_decision": {"terminal": terminal, "action": action, "reason": reason}}}},
    )


EVIDENCE = "Evidence strength is 'insufficient', below what a decision requires."


class UnresolvedReviewUsesRealRecordsTests(unittest.TestCase):
    def test_real_records_are_listed_in_korean_with_counts(self) -> None:
        records = tuple(_record(f"00000{i}", "collect_more_evidence", EVIDENCE) for i in range(3)) + (
            _record("999999", "expand_period", "Observation period is not yet long enough for a reliable read."),
            _record("111111", "hold", "done", terminal=True),
        )
        text = d._compose_runtime_unresolved_review("2026-11-17T12:30:00Z", audit_records_provider=lambda: records)
        self.assertIn("후속 조치가 필요한 연구 4건", text)
        self.assertIn("- 근거 추가 수집 3건: 근거가 부족해 판단하기 어려워요", text)
        self.assertIn("- 검증 기간 확대 1건: 관찰 기간이 아직 짧아 신뢰하기 어려워요", text)
        self.assertIn("000000", text)
        self.assertNotIn("111111", text)  # 종료된(terminal) 결정은 목록에서 빠진다
        self.assertNotIn("Evidence strength", text)

    def test_long_list_is_capped(self) -> None:
        records = tuple(_record(f"{i:06d}", "collect_more_evidence", EVIDENCE) for i in range(25))
        text = d._compose_runtime_unresolved_review("2026-11-17T12:30:00Z", audit_records_provider=lambda: records)
        self.assertIn("- 근거 추가 수집 25건:", text)
        self.assertIn(" 외 15건", text)
        listed = [line for line in text.splitlines() if line.startswith("  ")][0]
        self.assertEqual(listed.split(" 외 ")[0].count(","), d._UNRESOLVED_SHOW_MAX - 1)

    def test_unreadable_records_are_reported_not_hidden_as_none(self) -> None:
        def broken():
            raise sqlite3.OperationalError("no such table")

        text = d._compose_runtime_unresolved_review("2026-11-17T12:30:00Z", audit_records_provider=broken)
        self.assertIn("연구 기록을 읽지 못해", text)
        self.assertNotIn("연구는 없습니다", text)

    def test_no_provider_keeps_previous_empty_behavior(self) -> None:
        text = d._compose_runtime_unresolved_review("2026-11-17T12:30:00Z")
        self.assertIn("후속 조치가 필요한 연구는 없습니다.", text)

    def test_unknown_reason_passes_through(self) -> None:
        self.assertEqual(d._ko_reason("some brand new reason"), "some brand new reason")
        self.assertEqual(d._ko_reason(None), "사유 없음")


if __name__ == "__main__":
    unittest.main()
