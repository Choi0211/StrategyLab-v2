"""Gaon Agent Foundation V2 - conservative multi-intent segmentation."""

from __future__ import annotations

import unittest

from gaon.runtime.gaon_agent.multi_intent import recompose_answers, segment_turn


class SegmentTurnTests(unittest.TestCase):
    def test_single_question_is_one_segment(self) -> None:
        for text in ("이름이 뭐예요?", "삼성전자와 SK하이닉스 비교해줘", "단타 연구 왜 멈췄어요?"):
            self.assertEqual(len(segment_turn(text)), 1, text)

    def test_two_blank_line_separated_questions_split(self) -> None:
        segments = segment_turn("이름이뭔가요\n\n단타 전략 연구가 승격될만한게 나오려면 뭐가 필요할까요")
        self.assertEqual([s.text for s in segments], ["이름이뭔가요", "단타 전략 연구가 승격될만한게 나오려면 뭐가 필요할까요"])

    def test_multi_sentence_request_is_not_split(self) -> None:
        # ordinary prose with sentence punctuation stays one intent
        text = "국내 주식 전체를 대상으로 단타 전략을 연구해주세요. 실제 데이터로 백테스트해줘."
        self.assertEqual(len(segment_turn(text)), 1)

    def test_single_line_breaks_do_not_split(self) -> None:
        text = "안녕하세요\n오늘도 잘 부탁드립니다\n확인 부탁해요"
        self.assertEqual(len(segment_turn(text)), 1)

    def test_long_structured_brief_stays_one_segment(self) -> None:
        brief = "\n\n".join(f"섹션 {i}: 실제 데이터를 사용해서 이 전략을 분석해줘. " * 3 for i in range(6))
        self.assertEqual(len(segment_turn(brief)), 1)

    def test_enumerated_list_splits(self) -> None:
        segments = segment_turn("1. 이름이 뭐예요?\n2. 오늘 기분은 어때요?")
        self.assertEqual(len(segments), 2)

    def test_non_request_block_prevents_a_split(self) -> None:
        # second block is a bare statement, not its own ask -> keep intact
        self.assertEqual(len(segment_turn("이름이 뭐예요?\n\n그냥 그렇다고요")), 1)

    def test_segments_are_capped(self) -> None:
        segments = segment_turn("\n\n".join(["질문 하나 뭐예요?", "질문 둘 왜요?", "질문 셋 어때요?", "질문 넷 뭔가요?"]))
        # 4 request blocks exceed MAX_SEGMENTS -> do not split (fail safe)
        self.assertEqual(len(segments), 1)


class RecomposeTests(unittest.TestCase):
    def test_joins_and_dedupes(self) -> None:
        self.assertEqual(recompose_answers(("A", "", "B", "A")), "A\n\nB")


if __name__ == "__main__":
    unittest.main()
