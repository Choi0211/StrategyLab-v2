import unittest

from gaon.knowledge.v1_asset_reuse_audit import (
    FINAL_VERDICT,
    ReuseStatus,
    production_legacy_path_isolation_release_check,
    production_no_unintended_duplicate_engine_release_check,
    production_research_memory_continuity_release_check,
    production_v1_asset_reuse_audit_release_check,
    production_v1_v2_authoritative_path_release_check,
    production_v1_v2_final_integration_release_check,
    v1_asset_reuse_audit_payload,
)


class V1AssetReuseAuditTests(unittest.TestCase):
    def test_asset_matrix_has_final_complete_verdict(self) -> None:
        payload = v1_asset_reuse_audit_payload()

        self.assertEqual(FINAL_VERDICT, payload["verdict"])
        self.assertGreaterEqual(len(payload["matrix"]), 14)
        statuses = {row["reuse_status"] for row in payload["matrix"]}
        self.assertIn(ReuseStatus.REUSED_AND_EXTENDED.value, statuses)
        self.assertIn(ReuseStatus.REPLACED_INTENTIONALLY.value, statuses)
        self.assertNotIn(ReuseStatus.DUPLICATED_UNNECESSARILY.value, statuses)
        self.assertNotIn(ReuseStatus.MISSING_FROM_V2.value, statuses)

    def test_authoritative_path_keeps_production_components(self) -> None:
        payload = production_v1_v2_authoritative_path_release_check()

        self.assertEqual("pass", payload["safety"])
        checks = payload["checks"]
        self.assertTrue(checks["telegram_agent_importable"])
        self.assertTrue(checks["safe_tool_executor_importable"])
        self.assertTrue(checks["quant_partner_importable"])
        self.assertTrue(checks["real_research_importable"])

    def test_release_checks_pass_without_side_effects(self) -> None:
        checks = (
            production_v1_asset_reuse_audit_release_check,
            production_v1_v2_authoritative_path_release_check,
            production_no_unintended_duplicate_engine_release_check,
            production_research_memory_continuity_release_check,
            production_legacy_path_isolation_release_check,
            production_v1_v2_final_integration_release_check,
        )

        for check in checks:
            with self.subTest(check=check.__name__):
                payload = check()
                self.assertEqual("pass", payload["safety"])
                self.assertEqual("complete", payload["status"])
                self.assertFalse(payload["approval_required"])
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])


if __name__ == "__main__":
    unittest.main()
