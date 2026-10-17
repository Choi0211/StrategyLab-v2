from __future__ import annotations

import sqlite3
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import (
    LLMConversationBrain,
    LLMConversationSession,
    SQLiteConversationRepository,
)
from gaon.runtime.migrations import migrate

NOW = "2026-10-17T10:45:23Z"


class StaleCapabilityContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.repo = SQLiteConversationRepository(self.connection)
        self.brain = LLMConversationBrain(GaonRuntimeConfig(), self.repo)

    def _seed(self, detail: str) -> None:
        self.repo.upsert_session(
            LLMConversationSession(
                "session:stale-capability",
                "user:youngha",
                "telegram",
                "active",
                NOW,
                NOW,
                {
                    "conversation_mvp": {
                        "last_read_subject": {
                            "kind": "capability_limitation",
                            "subject_type": "capability_limitation",
                            "mission_id": None,
                            "detail_text": detail,
                            "updated_at": NOW,
                        }
                    }
                },
            )
        )

    def test_old_realtime_web_limitation_is_invalidated_when_web_search_is_available(self) -> None:
        self._seed("영하님, 지금은 실시간 정보(날씨·시세·환율·뉴스 등)를 조회할 수 있는 도구가 연결되어 있지 않아 최신 값을 확인할 수 없습니다.")
        self.assertIsNone(self.brain._read_subject_for("session:stale-capability"))

    def test_old_url_limitation_is_invalidated_when_url_fetch_is_available(self) -> None:
        self._seed("영하님, 저는 아직 링크를 직접 열어 내용을 가져올 수 없습니다.")
        self.assertIsNone(self.brain._read_subject_for("session:stale-capability"))

    def test_transient_youtube_auth_limitation_is_not_erased(self) -> None:
        self._seed("YouTube가 이 서버 IP에 로그인 확인을 요구합니다. 승인된 쿠키 파일이 필요합니다.")
        subject = self.brain._read_subject_for("session:stale-capability")
        self.assertIsNotNone(subject)
        self.assertIn("쿠키", subject["detail_text"])


if __name__ == "__main__":
    unittest.main()
