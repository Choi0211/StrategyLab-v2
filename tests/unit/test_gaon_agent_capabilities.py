"""Gaon Agent Foundation V2 - capability registry, need model, developer
boundary, tool view and multimodal descriptor unit tests."""

from __future__ import annotations

import unittest

from gaon.runtime.gaon_agent import (
    DEVELOPER_AGENT_CAPABILITIES,
    FORBIDDEN_IN_AGENT_LAYER,
    NeedAssessment,
    RequestedGoal,
    assess_from_registry,
    assert_not_privileged,
    capability_prompt_summary,
    default_capability_registry,
)
from gaon.runtime.gaon_agent.capabilities import (
    CHAMPION_PROMOTION,
    CODE_MODIFY_DEV,
    GENERAL_CONVERSATION,
    IMAGE_VISION,
    RESEARCH_MISSION_RUN,
    URL_FETCH,
    CapabilityState,
    CapabilityUnavailableError,
)
from gaon.runtime.gaon_agent.developer_boundary import PrivilegedActionError
from gaon.runtime.gaon_agent.multimodal import Modality, describe_multimodal_request
from gaon.runtime.gaon_agent.tools import non_production_tool_names, tool_capability_views


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_capability_registry()

    def test_only_genuinely_wired_capabilities_are_available(self) -> None:
        available = {c.id for c in self.registry.by_state(CapabilityState.AVAILABLE)}
        self.assertEqual(
            available,
            {
                "GENERAL_CONVERSATION", "RESEARCH_MISSION_READ", "STRATEGY_STATUS_READ", "MARKET_DATA_READ",
                "WEB_SEARCH", "URL_FETCH", "DOCUMENT_READ", "IMAGE_VISION", "VIDEO_METADATA",
                "VIDEO_TRANSCRIPT", "VIDEO_FRAME_ANALYSIS", "EVIDENCE_INGEST", "EVIDENCE_VALIDATE", "REPOSITORY_READ",
            },
        )

    def test_external_research_and_media_capabilities_are_available(self) -> None:
        for capability_id in (URL_FETCH, IMAGE_VISION, "WEB_SEARCH", "VIDEO_TRANSCRIPT", "DOCUMENT_READ"):
            self.assertEqual(self.registry.state(capability_id), CapabilityState.AVAILABLE)
            self.assertTrue(self.registry.is_available(capability_id))
        self.assertEqual(self.registry.state(CODE_MODIFY_DEV), CapabilityState.APPROVAL_REQUIRED)

    def test_privileged_capabilities_are_forbidden(self) -> None:
        for capability_id in FORBIDDEN_IN_AGENT_LAYER:
            self.assertEqual(self.registry.state(capability_id), CapabilityState.FORBIDDEN)

    def test_running_a_research_mission_requires_approval(self) -> None:
        self.assertEqual(self.registry.state(RESEARCH_MISSION_RUN), CapabilityState.APPROVAL_REQUIRED)

    def test_unknown_capability_id_fails_closed_to_unavailable(self) -> None:
        self.assertEqual(self.registry.state("NOT_A_REAL_CAPABILITY"), CapabilityState.UNAVAILABLE)

    def test_require_available_accepts_wired_and_rejects_unknown(self) -> None:
        with self.assertRaises(CapabilityUnavailableError):
            self.registry.require_available("NOT_A_REAL_CAPABILITY")
        self.assertIsNotNone(self.registry.require_available(URL_FETCH))
        self.assertIsNotNone(self.registry.require_available(GENERAL_CONVERSATION))

    def test_prompt_summary_never_advertises_an_unavailable_capability(self) -> None:
        summary = capability_prompt_summary(self.registry)
        self.assertIn("CAN do now", summary)
        lowered = summary.lower()
        self.assertIn("search the public web", lowered)
        self.assertIn("dedicated vision model", lowered)
        self.assertIn("only claim", lowered)
        self.assertIn("actually returned evidence", lowered)


class NeedAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_capability_registry()

    def test_unknown_capability_recommends_a_code_change_next_step(self) -> None:
        goal = RequestedGoal("future feature", required_capabilities=("FUTURE_CAPABILITY",))
        assessment = assess_from_registry(goal, self.registry)
        self.assertIsInstance(assessment, NeedAssessment)
        self.assertEqual(assessment.missing_capabilities, ("FUTURE_CAPABILITY",))
        self.assertFalse(assessment.is_fulfillable_now)
        self.assertFalse(assessment.code_change_potentially_required)

    def test_forbidden_capability_routes_to_a_safety_controller(self) -> None:
        goal = RequestedGoal("promote the champion", required_capabilities=(CHAMPION_PROMOTION,))
        assessment = assess_from_registry(goal, self.registry)
        self.assertEqual(assessment.forbidden_capabilities, (CHAMPION_PROMOTION,))
        self.assertFalse(assessment.is_fulfillable_now)
        self.assertIn("safety controller", assessment.recommended_next_step)

    def test_available_only_goal_is_fulfillable_now(self) -> None:
        goal = RequestedGoal("chat", required_capabilities=(GENERAL_CONVERSATION,))
        assessment = assess_from_registry(goal, self.registry)
        self.assertTrue(assessment.is_fulfillable_now)


class DeveloperBoundaryTests(unittest.TestCase):
    def test_capability_sets_are_disjoint(self) -> None:
        self.assertEqual(DEVELOPER_AGENT_CAPABILITIES & FORBIDDEN_IN_AGENT_LAYER, frozenset())

    def test_assert_not_privileged_blocks_forbidden_ids(self) -> None:
        for capability_id in FORBIDDEN_IN_AGENT_LAYER:
            with self.assertRaises(PrivilegedActionError):
                assert_not_privileged(capability_id)

    def test_assert_not_privileged_allows_developer_ids(self) -> None:
        for capability_id in DEVELOPER_AGENT_CAPABILITIES:
            assert_not_privileged(capability_id)  # no raise


class ToolCapabilityViewTests(unittest.TestCase):
    def test_fixture_tools_are_not_production_grade(self) -> None:
        import sqlite3

        from gaon.runtime.llm_tools import default_tool_registry
        from gaon.runtime.migrations import migrate

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        registry = default_tool_registry(connection)
        views = {view.name: view for view in tool_capability_views(registry)}
        self.assertIn("weather_current", views)
        self.assertFalse(views["weather_current"].production_grade)
        self.assertTrue(views["weather_current"].fixture_backed)
        self.assertFalse(views["web_search"].production_grade)
        self.assertIn("weather_current", non_production_tool_names(registry))
        self.assertTrue(views["krx_real_research"].production_grade)


class MultimodalDescriptorTests(unittest.TestCase):
    def test_inspect_request_for_media_is_recognised(self) -> None:
        ref = describe_multimodal_request("이 유튜브 영상 좀 봐줘")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.modality, Modality.VIDEO)
        self.assertEqual(describe_multimodal_request("이 스크린샷 분석해줘").modality, Modality.IMAGE)
        self.assertEqual(describe_multimodal_request("첨부한 파일 pdf 읽어줘").modality, Modality.DOCUMENT)

    def test_howto_question_is_not_a_media_inspect_request(self) -> None:
        self.assertIsNone(describe_multimodal_request("영상 편집은 어떻게 배워요"))
        self.assertIsNone(describe_multimodal_request("이름이 뭔가요"))


if __name__ == "__main__":
    unittest.main()
