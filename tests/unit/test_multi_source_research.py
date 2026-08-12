import unittest

from gaon.knowledge.multi_source_research import (
    AcquisitionState,
    DeterministicMultiSourceAdapter,
    MultiSourceResearchOrchestrator,
    MultiSourceResearchPlan,
    MultiSourceResearchPolicy,
    ProviderState,
    SourceCategory,
    production_community_idea_research_release_check,
    production_cross_source_conflict_release_check,
    production_evidence_fusion_release_check,
    production_multi_source_experiment_loop_release_check,
    production_multi_source_research_contract_release_check,
    production_research_prompt_injection_safety_release_check,
    production_source_independence_release_check,
    production_validation_sample_diagnostic_release_check,
    production_web_news_research_release_check,
    production_youtube_research_release_check,
)
from gaon.knowledge.telegram_autonomous_learning import production_autonomous_learning_payload_from_baseline


class MultiSourceResearchTest(unittest.TestCase):
    def test_release_checks_pass(self) -> None:
        checks = (
            production_multi_source_research_contract_release_check,
            production_web_news_research_release_check,
            production_youtube_research_release_check,
            production_community_idea_research_release_check,
            production_evidence_fusion_release_check,
            production_source_independence_release_check,
            production_cross_source_conflict_release_check,
            production_multi_source_experiment_loop_release_check,
            production_research_prompt_injection_safety_release_check,
            production_validation_sample_diagnostic_release_check,
        )
        for check in checks:
            with self.subTest(check=check.__name__):
                payload = check()
                self.assertEqual(payload["safety"], "pass")
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])

    def test_youtube_metadata_only_does_not_create_claims(self) -> None:
        plan = MultiSourceResearchPlan(
            plan_id="plan:youtube-metadata-only",
            symbol="005930",
            research_topic="strategy robustness",
            strategy_family="breakout",
            providers=(SourceCategory.YOUTUBE,),
            queries={SourceCategory.YOUTUBE.value: ("동영상 자료도 확인해줘",)},
            policy=MultiSourceResearchPolicy(),
        )
        result = MultiSourceResearchOrchestrator(
            (
                DeterministicMultiSourceAdapter(
                    SourceCategory.YOUTUBE,
                    state=ProviderState.SUCCESS,
                    metadata_only=True,
                ),
            )
        ).run(plan)
        self.assertEqual(result["claims_extracted"], 0)
        self.assertEqual(result["promotion_status"], "needs_real_validation")

    def test_metadata_only_or_fixture_evidence_does_not_unlock_production_promotion(self) -> None:
        baseline = _baseline_payload()
        plan = MultiSourceResearchPlan(
            plan_id="plan:metadata-only",
            symbol="005930",
            research_topic="strategy robustness",
            strategy_family="breakout",
            providers=(SourceCategory.WEB,),
            queries={SourceCategory.WEB.value: ("자료를 찾아서 검증해줘",)},
            policy=MultiSourceResearchPolicy(),
        )
        multi_source = MultiSourceResearchOrchestrator(
            (
                DeterministicMultiSourceAdapter(
                    SourceCategory.WEB,
                    state=ProviderState.SUCCESS,
                    metadata_only=True,
                    fixture_backed=False,
                ),
            )
        ).run(plan, validation_payload=baseline)
        external = {
            "state": "content_unavailable",
            "multi_source_research": multi_source,
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 연구해줘",
            symbol="005930",
            mode="research",
            baseline=baseline,
            external_research=external,
        )
        self.assertEqual(payload["promotion_status"], "needs_real_validation")
        self.assertFalse(payload["approval_required"])


def _baseline_payload() -> dict[str, object]:
    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": "fp:candidate", "rules": ["breakout", "volume"]}
    return {
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart",
                "fixture_backed": False,
                "rows": 378,
                "start_date": "2025-01-02",
                "end_date": "2026-07-24",
            }
        },
        "quality": {"status": "pass", "blocking_findings": []},
        "strategy": strategy,
        "backtest": {"source": "real", "metrics": {"trade_count": 3, "total_return": 0.03}},
        "candidates": [
            {
                "candidate_id": "candidate:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": "backtest:candidate",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": 4, "total_return": 0.05, "mdd": 0.02},
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
