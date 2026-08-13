# StrategyLab v2 Test Results

Status: Passed

## Hotfix 240.2 Production Validation Coverage & Research Horizon

- Targeted local verification:
  - `python -m py_compile src\gaon\research\krx_real_pipeline.py src\gaon\knowledge\multi_source_research.py src\gaon\knowledge\autonomous_quant_partner.py src\gaon\knowledge\telegram_autonomous_learning.py src\gaon\runtime\research_grounding.py src\gaon\runtime\cli.py`: PASS
  - `python -m unittest tests.unit.test_autonomous_quant_partner tests.unit.test_krx_real_pipeline -q`: PASS, 43 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint199_240_autonomous_quant_partner_release_checks_pass -q`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-validation-coverage-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-research-horizon-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-sample-sufficiency-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-backtest-signal-diagnostic-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-validation-window-integrity-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-validation-coverage-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-research-wiring-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 836 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 198 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS, whitespace clean; Windows line-ending warnings only
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass, no fabricated metrics, and no validation threshold relaxation.

## Hotfix 240.1 Real Production Autonomous Research Wiring

- Targeted local verification:
  - `python -m py_compile src\gaon\knowledge\telegram_autonomous_learning.py src\gaon\knowledge\autonomous_quant_partner.py src\gaon\runtime\research_grounding.py src\gaon\runtime\cli.py tests\unit\test_autonomous_quant_partner.py`: PASS
  - `python -m unittest tests.unit.test_autonomous_quant_partner -q`: PASS, 7 tests
  - `python -m unittest tests.unit.test_autonomous_learning_e2e -q`: PASS, 44 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_combined_autonomous_learning_request_routes_to_v2 tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1852_production_combined_request_prioritizes_v2_over_legacy_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_default_telegram_tool_path_blocks_release_fixture_promotion tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint199_240_autonomous_quant_partner_release_checks_pass -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-production-autonomous-research-wiring-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 833 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 198 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass, no fixture/metadata-only promotion evidence, no fabricated metrics/evidence.

## Sprint 199-240 Autonomous Quant Research Partner

- Targeted local verification:
  - `python -m py_compile src\gaon\knowledge\autonomous_quant_partner.py src\gaon\knowledge\telegram_autonomous_learning.py src\gaon\runtime\cli.py`: PASS
  - `python -m unittest tests.unit.test_autonomous_quant_partner -q`: PASS, 4 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint199_240_autonomous_quant_partner_release_checks_pass -q`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-provider-registry-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-authoritative-source-acquisition-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-source-diversification-planner-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-counter-evidence-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-validation-sufficiency-v2-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-iterative-research-loop-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-robust-strategy-validation-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-strategy-tournament-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-learning-memory-closed-loop-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-promotion-readiness-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-research-observability-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-quant-partner-acceptance-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 830 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 198 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass, no fixture/metadata-only promotion evidence, no fabricated metrics/evidence.

## Sprint 193-198 Multi-Source Autonomous Research

- Targeted local verification:
  - `python -m py_compile src\gaon\knowledge\multi_source_research.py src\gaon\knowledge\telegram_autonomous_learning.py src\gaon\runtime\cli.py`: PASS
  - `python -m unittest tests.unit.test_multi_source_research -q`: PASS, 3 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint193_198_multi_source_autonomous_research_release_checks_pass -q`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-multi-source-research-contract-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-web-news-research-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-youtube-research-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-community-idea-research-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-evidence-fusion-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-source-independence-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-cross-source-conflict-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-multi-source-experiment-loop-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-research-prompt-injection-safety-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-validation-sample-diagnostic-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 826 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 197 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass, no unrestricted crawling/paywall bypass, no fabricated metrics/evidence.

## Hotfix 192.3 Resilient Academic Source Fallback

- Targeted local verification:
  - `python -m unittest tests.unit.test_external_research_execution tests.unit.test_autonomous_learning_e2e -q`: PASS, 50 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint187_192_production_autonomous_learning_loop_release_checks_pass -q`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-relevant-academic-content-loop-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-academic-source-fallback-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-academic-source-budget-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-state-semantics-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 823 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 196 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass, no 403/paywall bypass, no fabricated metrics/evidence.

## Sprint 187-192 Integrated Autonomous Learning Production Loop

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_learning_e2e`: PASS, 33 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint187_192_production_autonomous_learning_loop_release_checks_pass`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-grounded-evidence-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-evidence-backed-hypothesis-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-strategy-experiment-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-authoritative-candidate-validation-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-robustness-ranking-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-human-promotion-gate-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-loop-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-execution-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-external-research-network-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-safe-content-acquisition-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-promotion-candidate-presentation-release-check --db :memory:`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 808 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 196 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only
- Schema: v36 unchanged.
- Safety: no live trading, no KIS/Broker orders, no automatic Champion promotion, no strategy mutation, no approval bypass.

## Sprint 186 Production Safe Content Acquisition

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_learning_e2e -q`: PASS, 25 tests
  - `python -m unittest tests.unit.test_external_research_execution tests.unit.test_source_content_acquisition -q`: PASS, 16 tests
  - `python -m gaon.runtime.cli gaon-production-safe-content-acquisition-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-external-research-network-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-execution-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-promotion-candidate-presentation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli research-context-isolation-release-check --db :memory:`: PASS
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint186_production_safe_content_acquisition_release_check_passes -v`: PASS, 1 test
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_default_telegram_tool_path_blocks_release_fixture_promotion -v`: PASS, 1 test
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 800 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 195 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 185.5 Production External Research Network Wiring

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_learning_e2e -q`: PASS, 20 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_default_telegram_tool_path_blocks_release_fixture_promotion -v`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-production-external-research-network-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-execution-release-check`: PASS
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_default_telegram_tool_path_blocks_release_fixture_promotion tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_production_autonomous_learning_execution_release_check_passes -q`: PASS, 2 tests
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 794 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 194 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-promotion-candidate-presentation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - `python -m gaon.runtime.cli research-context-isolation-release-check --db :memory:`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 185.4 Production Autonomous Learning Execution Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_learning_e2e -q`: PASS, 8 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_default_telegram_tool_path_blocks_release_fixture_promotion tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1854_production_autonomous_learning_execution_release_check_passes -q`: PASS, 2 tests
  - `python -m gaon.runtime.cli gaon-production-autonomous-learning-execution-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 782 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 194 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 185.3 Promotion Candidate Evidence Presentation Integrity

- Targeted local verification:
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1853_promotion_candidate_detail_followup_preserves_evidence_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1853_missing_metric_and_metadata_only_source_are_not_fabricated tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1853_promotion_candidate_context_is_chat_isolated tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1853_promotion_candidate_presentation_release_check_passes -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-promotion-candidate-presentation-release-check --db :memory:`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 776 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 192 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - `python -m gaon.runtime.cli research-context-isolation-release-check --db :memory:`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 185.2 Telegram Autonomous Learning Priority Routing

- Targeted local verification:
  - `python -m unittest tests.unit.test_multi_symbol_research.MultiSymbolResearchTests.test_autonomous_learning_v2_request_has_priority_over_real_research tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_autonomous_learning_continuation_keeps_symbol tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1852_production_combined_request_prioritizes_v2_over_legacy_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1852_v2_context_continuation_keeps_v2 -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 776 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 188 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS

## Hotfix 185.1 Telegram Autonomous Learning Routing

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_learning_e2e tests.unit.test_multi_symbol_research tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_combined_autonomous_learning_request_routes_to_v2 tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_autonomous_learning_continuation_keeps_symbol tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_external_research_continuation_keeps_current_target tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_autonomous_learning_missing_context_asks_target tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_approval_sounding_phrase_does_not_mutate tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1851_telegram_autonomous_learning_routing_release_check_passes -q`: PASS, 21 tests
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-learning-routing-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - `python -m gaon.runtime.cli research-context-isolation-release-check --db :memory:`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 776 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 185 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 175-185 Follow-up Autonomous Learning Execution Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_external_research_execution tests.unit.test_authoritative_experiment_execution tests.unit.test_autonomous_learning_e2e -q`: PASS, 10 tests
  - `python -m gaon.runtime.cli gaon-autonomous-external-research-execution-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-authoritative-experiment-execution-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check`: PASS
  - Sprint 175-185 release-check regression bundle: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 774 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 185 Human-gated Autonomous Research Promotion

- Targeted local verification:
  - `python -m unittest tests.unit.test_human_gated_promotion -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-human-gated-promotion-release-check`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-learning-production-gate-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 764 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 184 Promotion Candidate Gate

- Targeted local verification:
  - `python -m unittest tests.unit.test_promotion_gate -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-promotion-candidate-gate-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 760 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 183 Strategy Robustness Ranking

- Targeted local verification:
  - `python -m unittest tests.unit.test_robustness_ranking -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-robustness-ranking-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 755 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 182 Autonomous Validation Loop v2

- Targeted local verification:
  - `python -m unittest tests.unit.test_validation_loop_v2 -q`: PASS, 6 tests
  - `python -m gaon.runtime.cli gaon-validation-loop-v2-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 751 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 181 Strategy Experiment Builder

- Targeted local verification:
  - `python -m unittest tests.unit.test_strategy_experiment -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-strategy-experiment-builder-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 745 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 180 Evidence-backed Strategy Hypothesis

- Targeted local verification:
  - `python -m unittest tests.unit.test_evidence_hypothesis -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-evidence-backed-hypothesis-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 740 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 179 External Research Memory

- Targeted local verification:
  - `python -m unittest tests.unit.test_external_research_memory -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-external-research-memory-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 735 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 178 Autonomous Knowledge Research Loop

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_knowledge_loop -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-autonomous-knowledge-research-loop-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 731 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 177 Evidence Conflict Re-evaluation

- Targeted local verification:
  - `python -m unittest tests.unit.test_evidence_reevaluation -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-evidence-conflict-reevaluation-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 726 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 176 Normalized Claim Bridge

- Targeted local verification:
  - `python -m unittest tests.unit.test_content_claim_bridge -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-normalized-claim-bridge-release-check`: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 722 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Sprint 175 Safe Source Content Normalization

- Targeted local verification:
  - `python -m unittest tests.unit.test_content_normalization -q`: PASS, 7 tests
  - `python -m gaon.runtime.cli gaon-content-normalization-release-check`: PASS, schema v36 unchanged
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 717 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 163.5 Autonomous Research Candidate Identity Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion.AutonomousResearchCycleTests.test_telegram_payload_uses_continuation_state_to_stop_duplicate_candidates tests.unit.test_autonomous_completion.AutonomousResearchCycleTests.test_telegram_payload_canonicalizes_legacy_candidate_history_identity -q`: PASS, 2 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1634_progress_comparison_preserves_root_candidate_history tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1635_autonomous_candidate_identity_release_check_passes -q`: PASS, 2 tests
  - `python -m gaon.runtime.cli gaon-autonomous-candidate-identity-release-check --db :memory:`: PASS, schema v36
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 609 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 179 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Sprint 163 release-check regressions: PASS for Telegram autonomous routing, conversation context, progression, history, and candidate identity
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 163.4 Autonomous Research History Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion.AutonomousResearchCycleTests.test_telegram_payload_uses_continuation_state_to_stop_duplicate_candidates -q`: PASS
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1634_progress_comparison_preserves_root_candidate_history -q`: PASS
  - `python -m gaon.runtime.cli gaon-autonomous-research-history-release-check --db :memory:`: PASS, schema v36
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 608 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 178 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Sprint 152-163 release-check regressions: PASS in integration suite, including `gaon-autonomous-research-progression-release-check` and `gaon-autonomous-research-history-release-check`
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 163.3 Autonomous Research Progression Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion.AutonomousResearchCycleTests.test_telegram_payload_uses_continuation_state_to_stop_duplicate_candidates -q`: PASS
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1633_continuation_reuses_parent_state_and_stops_duplicates tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1633_progress_comparison_blocks_unsupported_deltas tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1633_presentation_after_progress_comparison_preserves_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1633_progression_context_is_chat_isolated tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1633_autonomous_progression_release_check_passes -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-autonomous-research-progression-release-check --db :memory:`: PASS, schema v36
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 608 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 176 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Sprint 152-163 release-check regressions: PASS in integration suite, including `gaon-conversation-release-check`, `gaon-conversational-reasoning-release-check`, `gaon-natural-conversation-release-check`, `gaon-presentation-integrity-release-check`, `gaon-conversational-research-execution-release-check`, `gaon-conversational-reexecution-integrity-release-check`, `gaon-telegram-autonomous-research-release-check`, and `gaon-autonomous-conversation-context-release-check`
  - `git diff --check`: PASS with Windows line-ending warnings only

## Hotfix 163.2 Autonomous Conversation Context Integrity

- Targeted local verification:
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_learning_summary_presentation_preserves_learning_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_autonomous_continuation_presentation_preserves_cycle_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_standard_research_presentation_still_works tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_comparison_rerun_presentation_keeps_comparison_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_presentation_context_is_chat_isolated tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1632_autonomous_context_release_check_passes -q`: PASS, 6 tests
  - `python -m gaon.runtime.cli gaon-autonomous-conversation-context-release-check --db :memory:`: PASS, schema v36
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 607 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 171 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Sprint 152 through 163 release-check commands, including `gaon-autonomous-conversation-context-release-check`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

## Hotfix 163.1 Telegram Autonomous Research Routing

- Targeted local verification:
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1631_autonomous_validate_routes_from_telegram_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1631_autonomous_critique_uses_prior_context_without_ids tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1631_autonomous_learning_query_reads_same_chat_context tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1631_autonomous_context_is_chat_isolated tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1631_telegram_autonomous_research_release_check_passes -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-telegram-autonomous-research-release-check --db :memory:`: PASS, schema v36
  - Existing Sprint 152, 153, 154, and 155 conversation release-check smoke tests: PASS
- Full local verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 607 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 165 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Sprint 152 through 163 release-check commands: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

## Sprint 163 Autonomous Research Completion

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 23 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 8 tests
  - `python -m gaon.runtime.cli gaon-autonomous-research-complete-release-check --db :memory:`: PASS, schema v36
- Full local verification:
  - `python -m pytest tests/unit -q`: NOT RUN, bundled Python does not include pytest
  - `python -m pytest tests/integration -q`: NOT RUN, bundled Python does not include pytest
  - `python -m unittest discover -s tests/unit -q`: PASS, 607 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 160 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `git diff --check`: PASS

## Sprint 162 Operational Autonomous Research

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 22 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 7 tests
  - `python -m gaon.runtime.cli gaon-operational-autonomous-research-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.

## Sprint 161 Autonomous Research Cycle

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 18 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 6 tests
  - `python -m gaon.runtime.cli gaon-autonomous-research-cycle-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.

## Sprint 160 Autonomous Learning Memory Integration

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 15 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 5 tests
  - `python -m gaon.runtime.cli gaon-autonomous-learning-memory-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.

## Sprint 159 Research Critic / Improvement / Retest

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 12 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 4 tests
  - `python -m gaon.runtime.cli gaon-research-critic-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.

## Sprint 158 Strategy Candidate Generation

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 9 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 3 tests
  - `python -m gaon.runtime.cli gaon-strategy-candidate-generation-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Sprint 157 Autonomous Research Planner

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 7 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 2 tests
  - `python -m gaon.runtime.cli gaon-autonomous-research-planner-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Sprint 156 Adaptive Research Validation

- Targeted local verification:
  - `python -m unittest tests.unit.test_autonomous_completion -q`: PASS, 4 tests
  - `python -m unittest tests.integration.test_autonomous_completion_flow -q`: PASS, 1 test
  - `python -m gaon.runtime.cli gaon-adaptive-validation-release-check --db :memory:`: PASS, schema v36
- Full verification: PENDING until Sprint 163 completion.
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Hotfix 155.1 Conversational Re-execution Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_research_execution tests.unit.test_conversational_mvp -q`: PASS, 36 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests -q`: PASS, 50 tests
  - `python -m gaon.runtime.cli gaon-conversational-reexecution-integrity-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 584 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 152 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Existing Sprint 152~155 release checks: PASS
  - `git diff --check`: PASS
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Sprint 155 Conversational Research Execution

- Targeted local verification:
  - `python -m py_compile src\gaon\runtime\conversational_research_execution.py src\gaon\runtime\llm_conversation.py src\gaon\runtime\conversational_mvp.py src\gaon\runtime\llm_tools.py src\gaon\research\krx_real_pipeline.py src\gaon\runtime\cli.py`: PASS
  - `python -m gaon.runtime.cli gaon-conversational-research-execution-release-check --db :memory:`: PASS, schema v36
  - `python -m unittest tests.integration.test_telegram_conversation_agent -v`: PASS, 46 tests
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 578 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 148 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - Existing Sprint 152~154 release checks: PASS through integration discover and targeted CLI output
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Hotfix 154.1 Presentation State and Grounding Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_mvp -v`: PASS, 24 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1541_presentation_state_and_grounding_integrity tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_hotfix1541_presentation_integrity_release_check_passes -v`: PASS, 2 tests
  - `python -m gaon.runtime.cli gaon-presentation-integrity-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 572 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 141 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-natural-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-presentation-integrity-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Sprint 154 Natural Conversation & Teaching Engine

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_mvp -v`: PASS, 21 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint154_natural_conversation_release_check_passes tests.integration.test_telegram_conversation_agent.TelegramConversationAgentTests.test_sprint154_telegram_presentation_followups_reuse_context_and_preferences -v`: PASS, 2 tests
  - `python -m gaon.runtime.cli gaon-natural-conversation-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 569 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 139 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-natural-conversation-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Sprint 153 Conversational Reasoning & Explanation Engine

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_mvp -v`: PASS, 16 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent -v`: PASS, 35 tests
  - `python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 564 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 137 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Hotfix 152.3 Result Units and Presentation Integrity

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_mvp -v`: PASS, 11 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent -v`: PASS, 32 tests
  - `python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 559 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 134 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Hotfix 152.2 Telegram Follow-up Persistence and Typo Tolerance

- Targeted local verification:
  - `python -m unittest tests.unit.test_conversational_mvp -v`: PASS, 9 tests
  - `python -m unittest tests.integration.test_telegram_conversation_agent -v`: PASS, 31 tests
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 557 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 133 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only
- Note: `python -m pytest ...` was not executed in this local desktop runtime because pytest is not installed in the bundled Python environment; equivalent `unittest` commands are used for local verification.

## Hotfix 152.1 Conversational Follow-up Context Integrity

- Targeted local verification:
  - `tests.unit.test_conversational_mvp`: PASS, 7 tests
  - Hotfix 152.1 Telegram targeted integration tests: PASS, 7 tests
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS, schema v36
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit -q`: PASS, 555 tests
  - `python -m unittest discover -s tests/integration -q`: PASS, 130 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

## Sprint 152 Gaon Conversational MVP

- Targeted local verification:
  - `tests.unit.test_conversational_mvp`: PASS, 5 tests
  - Sprint 152 Telegram targeted integration tests: PASS, 6 tests
  - `gaon-conversation-release-check --db :memory:`: PASS, schema v36
- Full verification:
  - `python -m unittest discover -s tests/unit`: PASS, 553 tests
  - `python -m unittest discover -s tests/integration`: PASS, 124 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:`: PASS
  - `python -m gaon.runtime.cli gaon-conversation-release-check --db .\gaon-runtime-sprint152.sqlite`: PASS
  - `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

## Sprint 151 Dynamic KRX Universe Selection

- Unit: `tests.unit.test_krx_universe`
  - trading-value ranking is descending and deterministic
  - equal trading values use canonical symbol ascending tie-breaks
  - invalid market, invalid date, invalid metric, invalid size, and non-trading selection date fail closed
  - zero-volume rows, zero-trading-value rows, duplicate symbols, and user exclusions are removed with explicit reasons
  - Yahoo-style suffix symbols canonicalize to six-digit KRX symbols
  - provider failure fails closed
  - explicit symbols keep priority over a dynamic universe result
  - dynamic universe result connects to multi-symbol research
  - read-only `krx_universe_select` safe tool succeeds without trading side effects
- Integration: `tests.integration.test_krx_universe_flow`
  - `krx-universe-select --json` returns readable deterministic JSON
  - `krx-universe-release-check` passes
  - existing explicit `multi-symbol-research-release-check` remains compatible
- Full verification:
  - `python -m unittest discover -s tests/unit`: PASS, 548 tests
  - `python -m unittest discover -s tests/integration`: PASS, 118 tests
  - `python scripts/verify_release.py`: PASS
  - `python -m gaon.runtime.cli krx-universe-release-check`: PASS
  - `python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon`: PASS
  - `git diff --check`: PASS
- Note: `python -m pytest ...` was not executed because pytest is not installed in the bundled Python runtime.
- Production real-universe provider validation: PENDING PRODUCTION VERIFICATION.

## Hotfix 150.5 Production Multi-Symbol Yahoo Registry Alignment

- Closeout unit: `tests.unit.test_runtime_service`
  - `deployment-import-path-check` passes when `gaon` imports from the project `src/gaon`
  - `deployment-import-path-check` fails closed when the expected source path does not match
- Unit: `tests.unit.test_krx_real_pipeline`
  - production inspection path canonicalizes Yahoo suffix symbols before registry lookup
  - `000660.KS` classifies `2022-01-03` and `2022-05-09` as provider gaps
  - `000660.KS` classifies the common 2022 zero-volume anomaly set plus `2022-03-11`, `2022-03-16`, and `2022-03-21` as registered provider zero-volume anomalies
  - per-symbol zero-volume anomaly dates are tested from VPS production evidence as common dates plus symbol-specific additions
- CLI release check:
  - `python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>`

## Hotfix 150.4 Yahoo Multi-Symbol Data Quality

- Unit: `tests.unit.test_krx_real_pipeline`
  - `historical_krx_data_quality_release_check` validates the five-symbol Sprint 141-150 research universe
  - common provider gaps `2022-01-03` and `2022-05-09` remain Yahoo provider gaps, not KRX holidays
  - symbol-specific provider gaps stay isolated to `000660`, `005380`, and `035420`
  - verified 2022 zero-volume anomaly bars are excluded for `005930`, `000660`, `005380`, `035420`, and `051910`
  - unregistered symbols and unregistered zero-volume bars remain blocking
- CLI release check:
  - `python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>`

## Hotfix 150.3 Multi-Symbol History Intent Collision

- Unit: `tests.unit.test_multi_symbol_research`
  - `기록해줘` in a multi-symbol execution request routes to `multi_symbol_research`
  - explicit history query routes to `multi_symbol_research_history`
  - explicit status query routes to `multi_symbol_research_status`
  - production long Telegram request parses as `multi_symbol_research`
  - production long Telegram request reports `execution_intent=true`, `history_intent=false`, `status_intent=false`
- Integration: `tests.integration.test_telegram_conversation_agent`
  - full production Telegram path persists a multi-symbol run, per-symbol evidence, candidate evidence, and universe snapshot
  - duplicate Telegram message idempotency keeps one persisted run
- CLI release check:
  - `python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>`

## Hotfix 150.2 Production Multi-Symbol Routing Diagnostics

- Unit: `tests.unit.test_multi_symbol_research`
  - production Korean multi-symbol request diagnostic selects `tool_read_only_authoritative`
  - selected tool is `multi_symbol_research`
  - explicit five-symbol KRX universe and `2021-07-25~2026-07-24` period are extracted
  - safety-boundary text does not trigger generic fallback
- Integration: `tests.integration.test_multi_symbol_research_flow`
  - `telegram-routing-debug --text-file <production request> --json` runs as a read-only CLI diagnostic
- CLI release check:
  - `python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>`

## Hotfix 150.1 Telegram Multi-Symbol Routing

- Unit: `tests.unit.test_multi_symbol_research`
  - production Korean multi-symbol request routes to `multi_symbol_research`
  - explicit KRX symbols are extracted as `005930,000660,005380,035420,051910`
  - request period is extracted as `2021-07-25~2026-07-24`
  - single-symbol retest and real-research routing remain unchanged
- Integration: `tests.integration.test_telegram_conversation_agent`
  - production Telegram multi-symbol request uses `tool_read_only_authoritative`
  - `provider_calls=0`
  - multi-symbol run, per-symbol evidence, candidate evidence, and universe snapshot persist
  - duplicate Telegram message idempotency prevents a second persisted run
- CLI release check:
  - `python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>`

## Hotfix 140.7 Yahoo KRX Zero Volume Anomaly Classification

- Unit: `tests.unit.test_krx_real_pipeline`
  - registered `005930` Yahoo zero-volume anomaly bars are excluded from backtest input
  - registered anomalies are reported as `provider_zero_volume_anomaly`
  - unregistered zero-volume bars remain blocking
- CLI release check:
  - `python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>`

## Hotfix 140.6 Historical KRX Data Quality Classification

- Unit: `tests.unit.test_krx_real_pipeline`
  - `2023-05-29` is excluded as a KRX closure
  - `2022-01-03` and `2022-05-09` remain KRX open dates
  - Yahoo `005930` symbol-specific provider gaps do not leak into other symbols
  - unregistered zero-volume bars remain blocking and inspectable
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `historical-krx-data-quality-release-check` repeats on one persistent SQLite DB
- CLI release check:
  - `python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>`

## Hotfix 140.3 Historical KRX Trading Calendar Accuracy

- Unit: `tests.unit.test_krx_real_pipeline`
  - 2023/2024 public holidays, election day, Labor Day, temporary holidays, and year-end closures are excluded from expected KRX trading dates
  - `2025-09-19` remains exchange-open and is not treated as a KRX holiday
  - historical Yahoo 3-year sample leaves only `2025-09-19` as `provider_gap`
  - unknown historical missing trading days remain blocking
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `historical-krx-calendar-release-check` repeats on one persistent SQLite DB
- CLI release check:
  - `python -m gaon.runtime.cli historical-krx-calendar-release-check --db <db>`

## Hotfix 140.2 Telegram Retest Persistence Visibility

- Unit: `tests.unit.test_autonomous_retest`
  - production-style `autonomous-retest:*` run IDs are not filtered as release-check/test artifacts
  - status/history payloads expose persisted metrics and quality finding lineage
- Integration: `tests.integration.test_telegram_conversation_agent`
  - production-equivalent Telegram retest requests persist runs, evidence, and period plans to the runtime DB
  - reopening the same DB preserves status/history visibility
  - duplicate Telegram message IDs do not store a second retest run
  - persistence failure returns a visible fallback instead of a successful research report
- Integration: `tests.integration.test_autonomous_retest_flow`
  - `telegram-retest-persistence-release-check` remains isolated and leaves the target DB retest tables unchanged
- CLI release check:
  - `python -m gaon.runtime.cli telegram-retest-persistence-release-check --db <db>`

## Hotfix 140.1 Telegram Autonomous Retest Routing

- Unit: `tests.unit.test_autonomous_retest`
  - explicit Korean retest execution requests route to `research_retest`
  - English `retest` / `expand period` requests route to `research_retest`
  - status/history requests remain read-only status/history routes
- Integration: `tests.integration.test_telegram_conversation_agent`
  - production-equivalent Korean Telegram retest request uses `tool_read_only_authoritative`
  - provider calls remain `0`
  - `research_retest` audit is appended
  - `krx_real_research` is not called
  - final response includes stop reason, period evidence, real provenance, and TESTED candidate comparison

## Sprint 131-140 Autonomous Retest Pipeline

- Unit: `tests.unit.test_autonomous_retest`
  - insufficient sample triggers a retest decision
  - adaptive period planner expands deterministically through 6m, 18m, 3y, and 5y
  - explicit user period boundaries stop silent expansion
  - orchestrator preserves strategy and assumptions fingerprints
  - final release-check retest reaches `min_trades`
  - candidate A/B/C results are TESTED and remain advisory
  - read-only safe tools `research_retest_status` and `research_retest_history` expose no order/promotion/apply capability
- Integration: `tests.integration.test_autonomous_retest_flow`
  - `autonomous-retest-release-check` repeats three times on one persistent SQLite DB
  - release-check fixture writes are isolated and leave production retest state unchanged
  - schema v35 stores retest runs, period plans, and retest evidence for explicit persisted diagnostic/demo runs without applying strategy config
  - `research-retest-demo --persist`, `research-retest-status`, and `research-retest-history` CLI smoke paths pass
- CLI release check:
  - `python -m gaon.runtime.cli autonomous-retest-release-check --db <db>`

## Sprint 121-130 Research Operations

- Unit: `tests.unit.test_research_operations`
  - insufficient sample is detected and period expansion is recommended
  - statistical confidence is capped when sample size is insufficient
  - dominant Challenger requires real, non-fixture, blocking-finding-free evidence
  - recommendation does not mutate strategy configuration before approval
  - approval applies strategy configuration and rollback restores the previous config
  - fixture evidence cannot drive configuration changes
  - `research_operation_status` is read-only and preserves no-order/no-promotion flags
  - release-check artifacts are hidden from `research_operation_status`
  - cleanup dry-run changes no rows and cleanup apply removes only artifacts
  - real user reports and approved configs remain visible
- Integration: `tests.integration.test_research_operations_flow`
  - `research-ops-release-check` repeats three times on one persistent SQLite DB
  - release-check fixture writes are isolated and leave production research state unchanged
  - cleanup CLI dry-run/apply removes persisted demo artifacts while recording cleanup audit
- CLI release check:
  - `python -m gaon.runtime.cli research-ops-release-check --db <db>`
  - `python -m gaon.runtime.cli research-ops-cleanup --db <db> --dry-run`

## Hotfix 120.7 Structural Authoritative Grounding Validator

- Unit: `tests.unit.test_research_grounding`
  - `wins=2`, `win=2`, and `승리 2회` pass only when `BacktestResult.metrics["wins"] == 2`
  - `loss=1`, `trades=3`, `MDD 5.2%`, `return 4.7%`, and `PF 1.42` pass only when backed by structured metrics
  - unrelated raw output numbers do not allow `trade_count=4`
  - unsupported `PF`, mismatched `win`, mismatched `trade_count`, mismatched MDD, RSI, MA, volume multiplier, stop, and take-profit claims remain blocked
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `structural-authoritative-grounding-release-check` repeats three times on one persistent SQLite DB
  - Telegram strict real-research release check continues to append tool audit records
- CLI release check:
  - `python -m gaon.runtime.cli structural-authoritative-grounding-release-check --db <db>`

## Hotfix 120.6 Authoritative Backtest Metric Grounding

- Unit: `tests.unit.test_research_grounding`
  - deterministic `krx_real_research` renderer validates against its own authoritative structured output
  - `wins`, `losses`, `trade_count`, `MDD`, `PF`, and return aliases pass only when values match the authoritative result
  - fabricated `win`, `loss`, `trade_count`, `MDD`, RSI, MA, and volume multiplier claims remain blocked
  - renderer invariant is tested with varied wins/losses/trades/MDD/return values
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `authoritative-renderer-grounding-release-check` repeats three times on one persistent SQLite DB
  - `telegram-strict-real-research-release-check` repeats three times and appends `krx_real_research` tool audit records
- CLI release check:
  - `python -m gaon.runtime.cli authoritative-renderer-grounding-release-check --db <db>`

## Hotfix 120.2 Real Provider Gap Classification

- Unit: `tests.unit.test_krx_real_pipeline`
  - `2025-09-19` remains an exchange-open KRX trading date
  - Yahoo `2025-09-19` missing bar is classified as `provider_gap`
  - provider anomaly policy does not affect other providers
  - provider-gap-only real datasets are research/release eligible
  - unknown missing trading dates, malformed OHLCV, and duplicates remain blocking
  - Korean research reports disclose provider gaps
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `provider-gap-release-check` repeats three times on one persistent SQLite DB
  - schema remains v33
- CLI release checks:
  - `python -m gaon.runtime.cli provider-gap-release-check --db <db>`
  - `python -m gaon.runtime.cli real-krx-data-release-check --db <db>` allows provider-gap-only warnings

## Hotfix 120.1 KRX Trading Calendar Quality

- Unit: `tests.unit.test_krx_real_pipeline`
  - weekends are excluded from KRX daily missing-date checks
  - deterministic KRX non-trading dates are excluded from missing-date checks
  - actual missing trading days still produce `missing_dates`
  - malformed OHLCV and duplicate trading days remain quality findings
  - real/fixture provenance remains unchanged
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `krx-trading-calendar-release-check` repeats three times on one persistent SQLite DB
  - schema remains v33
- CLI release checks:
  - `python -m gaon.runtime.cli krx-trading-calendar-release-check --db <db>`
  - `python -m gaon.runtime.cli real-krx-data-release-check --db <db>` when real Yahoo access is enabled

## Real KRX Data Activation

- Unit: `tests.unit.test_krx_real_pipeline`
  - Yahoo chart provider response parsing
  - `source=real` and `fixture_backed=false` provenance
  - empty, malformed, and failing provider responses return unavailable state
  - release check rejects fixture providers
  - env provider selection requires explicit real provider
- Unit: `tests.unit.test_gaon_runtime_collaboration`
  - real market data env defaults to disabled fixture mode
  - real mode rejects fixture provider configuration
- CLI:
  - `real-krx-data-release-check` fails closed unless `GAON_REAL_MARKET_DATA_ENABLED=true`

## Sprint 111-120 KRX Real Research Pipeline

- Unit: `tests.unit.test_krx_real_pipeline`
  - StrategySpec provenance and fixture metadata isolation
  - fixture/real source isolation and reproducible dataset fingerprints
  - deterministic rule-based backtest with cost application
  - prior-bar look-ahead prevention through breakout and MA calculations
  - walk-forward chronological split
  - Korean report and research memory persistence
- Integration: `tests.integration.test_krx_real_research_pipeline_flow`
  - `krx-real-research-release-check` repeats three times on one persistent SQLite DB
  - read-only safe tool `krx_real_research` produces fixture-disclosed Korean report
  - parser, real-backtest, and full KRX research release checks pass
- CLI release checks:
  - `python -m gaon.runtime.cli strategy-parser-release-check --db <db>`
  - `python -m gaon.runtime.cli real-backtest-release-check --db <db>`
  - `python -m gaon.runtime.cli krx-real-research-release-check --db <db>`

## Hotfix 110.2 Korean Response Language Consistency

- Unit: `tests.unit.test_research_grounding`
  - Korean quality-score missing-data response is deterministic Korean text
  - Korean strategy critique translates internal English findings
  - Provider English tool-result answers fall back to grounded Korean formatting
  - `<output>` and `<response>` wrappers are removed
  - English user requests may still receive English responses
- Integration: `tests.integration.test_korean_response_release_check`
  - `korean-response-release-check` runs three times on one persistent SQLite DB
  - generated conversation message IDs remain unique
  - schema version remains unchanged
- CLI release check: `python -m gaon.runtime.cli korean-response-release-check --db <db>`

## Hotfix 110.1 Research Grounding Context Isolation

- Unit: `tests.unit.test_research_grounding`
  - user strategy context remains isolated from fixture/default candidate fields
  - provider tool-result payloads exclude fixture parameters, fixture metrics, and regime metadata
  - `1.5x`, `max_risk_pct=1.0`, and `regime_tags` leakage fails tests
  - quality-score missing-data fallback is deterministic Korean text
- Integration: `tests.integration.test_research_context_isolation_release_check`
  - `research-context-isolation-release-check` runs three times on one persistent SQLite DB
  - generated conversation message IDs remain unique
  - schema version remains unchanged
- CLI release check: `python -m gaon.runtime.cli research-context-isolation-release-check --db <db>`

## Hotfix Research Grounding and Telegram Routing

- Unit: `tests.unit.test_research_grounding`
  - strategy weakness responses do not fabricate fixture metrics
  - user-provided metrics remain allowed when explicitly recorded as facts
  - tool-returned backtest metrics remain allowed
  - empty memory returns no stored match without access-error wording
  - improvement routing works even when memory is empty
  - quality-score responses use quality fields only
  - provider tool synthesis falls back to deterministic grounded formatting when fixture metrics are fabricated
- Integration: `tests.integration.test_research_grounding_release_check`
  - `research-grounding-release-check` runs three times on one persistent SQLite DB
  - generated conversation message IDs remain unique
  - schema version remains unchanged
- CLI release check: `python -m gaon.runtime.cli research-grounding-release-check --db <db>`

## Sprint 56-60 LLM Agent

- Provider tests: fake OpenAI-compatible content and tool-call responses.
- Tool calling tests: single tool, multi-tool, unknown tool, malformed/denied tool, tool limit.
- Multi-turn tests: Champion, Runtime, v5 pipeline follow-ups and stale result refresh.
- Planner tests: safe multi-step, overflow, approval boundary, repository round-trip.
- Security tests: shell, SQL, secret, approval, deployment, broker-order prompt injection.

## Sprint 51-55 LLM Brain

- Unit: LLM conversation, contextual memory orchestration, safe tools, CLI hardening.
- Integration: Telegram conversational agent, persistent offset reuse, duplicate protection, restart replay prevention.
- Release verification: `python scripts/verify_release.py`

## Sprint 47 Strategy Execution Runtime

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 308 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_strategy_execution tests.unit.test_runtime_service`
  - Result: `Ran 11 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 57 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_strategy_execution_flow`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `paper_revalidation_policy_v1`
  - `strategy_execution_policy_v1`
- CLI smoke: Passed
  - `db-check --db <temp>`
  - `paper-revalidation-policy-show`
  - `paper-revalidate`
  - `execution-policy-show`
  - `execution-plan --mode paper`
  - `execution-run`
  - `execution-plan --mode live`
- `git diff --check`: Passed
- Coverage:
  - default mode `DISABLED`
  - missing Champion blocked
  - stale Champion blocked
  - PAPER plan allowed for active Champion
  - PAPER execution reuses existing adapter stack
  - HOLD blocks LIVE
  - KILL blocks execution
  - ROLLBACK_RECOMMENDED blocks LIVE
  - LIVE_ELIGIBLE still blocked because broker adapter is unavailable
  - persistence and restart recovery
  - v17-to-v18 migration
  - events, metrics, and CLI smoke
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - live disabled by default
  - no automatic Champion promotion
  - no automatic rollback
  - no automatic approval
  - no MyMoneyGuard dependency

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

- Unit tests: Passed
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_paper_revalidation tests.unit.test_runtime_service`
  - Result: `Ran 12 tests`
  - Status: `OK`
- Integration tests: Passed
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_paper_revalidation_flow`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Coverage:
  - completed healthy paper session -> `LIVE_ELIGIBLE`
  - incomplete session -> `HOLD`
  - insufficient trades -> `HOLD`
  - excessive drawdown -> `KILL`
  - critical execution error -> `KILL`
  - fingerprint mismatch -> `KILL`
  - moderate drawdown deterioration -> `ROLLBACK_RECOMMENDED`
  - missing optional metrics -> `REVIEW`
  - deterministic repeated report
  - events and metrics
  - persistence and v16-to-v17 migration
  - CLI smoke for policy, revalidate, show, and history
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic rollback
  - no automatic approval
  - no Champion Registry mutation
  - no MyMoneyGuard dependency

## Sprint 45 Paper Trading Forward Test

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 297 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_paper_forward tests.unit.test_champion_registry tests.unit.test_runtime_service`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 53 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_paper_forward_flow tests.integration.test_champion_registry_flow`
  - Result: `Ran 4 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.champion_registry`
  - `import gaon.adapters.paper_forward`
- CLI smoke: Passed
  - `db-check --db <temp>`
  - `champion-bootstrap`
  - `paper-session-create`
  - `paper-session-start`
  - `paper-session-simulate-order`
  - `paper-session-summary`
  - `paper-session-complete`
- `git diff --check`: Passed
- Coverage:
  - only active Champion can create a paper session
  - stale Champion rejected
  - fingerprint mismatch rejected
  - lifecycle transitions
  - duplicate start handling
  - pause and resume
  - cancel and complete
  - PaperTradingAdapter stack reused
  - deterministic performance summary
  - events and metrics
  - persistence round trip
  - v15-to-v16 migration
  - CLI smoke
  - live intent remains approval-blocked
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic trading
  - no automatic approval
  - no Paper-to-Live automatic promotion
  - no MyMoneyGuard dependency

## Sprint 44 Champion Registry and Approval Promotion

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 292 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_champion_registry tests.unit.test_champion_challenger tests.unit.test_runtime_service`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 51 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_champion_registry_flow tests.integration.test_champion_challenger_flow`
  - Result: `Ran 5 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Coverage:
  - explicit first Champion bootstrap
  - duplicate bootstrap rejection
  - valid promotion request from `promotion_candidate`
  - `keep_champion`, `review`, and missing evaluations rejected
  - approval updates active Champion
  - rejection leaves Champion unchanged
  - duplicate approval idempotency
  - history preservation
  - rollback to previous Champion
  - rollback without previous Champion rejected
  - persistence round trip
  - v14-to-v15 migration
  - events, metrics, and CLI smoke
- Safety:
  - no automatic Champion promotion
  - no direct `PROMOTION_CANDIDATE` activation
  - no active strategy switching
  - no live KIS
  - no broker orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency

## Sprint 43 Champion / Challenger Evaluation Engine

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 286 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_champion_challenger`
  - Result: `Ran 5 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 49 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_champion_challenger_flow`
  - Result: `Ran 3 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.champion`
- CLI smoke: Passed
  - `champion-policy-show`
  - `db-check --db :memory:`
  - backtest persistence -> validation persistence -> champion-evaluate -> champion-evaluation-show -> champion-evaluation-history
- Coverage:
  - Validation PASS Challenger evaluation
  - Validation FAIL -> KEEP_CHAMPION
  - Validation REVIEW -> REVIEW
  - identical fingerprint blocking
  - return improvement threshold
  - MDD degradation threshold
  - profit factor comparison
  - missing optional metric handling
  - score cannot override hard gates
  - deterministic repeated evaluation
  - persistence, event emission, metrics, CLI smoke, planner route, and v13-to-v14 migration
- Safety:
  - no automatic Champion promotion
  - no active strategy switching
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency
  - no arbitrary shell execution
  - no paid-provider fallback

## Sprint 42 Strategy Validation Engine

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 281 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_strategy_validation_engine`
  - Result: `Ran 8 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 46 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_strategy_validation_flow`
  - Result: `Ran 4 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.validation`
- CLI smoke: Passed
  - `validation-policy-show`
  - `db-check --db :memory:`
  - backtest-run -> validation-run -> validation-show -> validation-history
- Coverage:
  - strong result PASS
  - excessive MDD FAIL
  - insufficient trade count FAIL
  - missing optional metric REVIEW
  - missing fingerprint FAIL
  - short sample period REVIEW
  - deterministic score
  - hard-fail overrides high score
  - overfitting heuristic warning
  - invalid drawdown range rejection
  - multi-run aggregation and catastrophic window detection
  - event emission, metrics, persistence round trip, CLI smoke, Research Agent route, and v12-to-v13 migration
- Safety:
  - no Champion promotion
  - no active strategy switching
  - no live KIS
  - no broker orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency
  - no paid-provider fallback

## Hotfix Telegram Runtime Worker and systemd Service

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 273 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_runtime_service`
  - Result: `Ran 6 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 42 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_runtime_service_flow`
  - Result: `Ran 3 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `gaon.runtime.cli run --once --db :memory:`
- systemd validation: Passed
  - `ExecStart` points to persistent `gaon.runtime.cli run --db /var/lib/strategylab/gaon-runtime.sqlite`
- Scope:
  - `GaonRuntimeService` can run a bounded Telegram polling tick
  - persisted Telegram offset is reused
  - duplicate updates do not resend
  - disabled and dry-run runtime does not call the live Telegram network
  - transient Telegram failures are recorded without terminating the runtime
  - `run --once` performs one bounded tick
  - systemd runs persistent `gaon.runtime.cli run --db /var/lib/strategylab/gaon-runtime.sqlite`
  - no live KIS, real trading, automatic approval, MyMoneyGuard dependency, or paid provider fallback

## Hotfix Telegram Poll Offset Persistence

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 270 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 40 tests`
  - Status: `OK`
- Targeted Telegram tests: Passed
  - Unit: `Ran 14 tests`
  - Integration: `Ran 8 tests`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `telegram-poll-once --dry-run --db runtime.sqlite`
- Scope:
  - existing SQLiteTelegramStateRepository reused
  - saved offset used when explicit `--offset` is omitted
  - explicit `--offset` has precedence
  - processed message duplicate protection prevents repeated replies
  - sent, duplicate, unauthorized, and ignored updates advance offset safely
  - no MyMoneyGuard, private repository, live trading, or security gate changes

## Sprint 41 v1 Backtest Adapter Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 265 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 39 tests`
  - Status: `OK`
- Targeted Sprint 41 tests: Passed
  - Unit: `Ran 6 tests`
  - Integration: `Ran 3 tests`
- Scope:
  - schema v12 migration from v11
  - safe BacktestAdapter contract
  - deterministic fake adapter
  - local process boundary tests for timeout, non-zero exit, invalid JSON, and bounded output
  - normalized result contract, optional metric handling, fingerprint reproducibility, persistence, duplicate request protection, lifecycle events, metrics, Executive Planner to Research Agent flow, and CLI smoke
  - no Champion promotion, active strategy switching, live KIS, broker credentials, real orders, MyMoneyGuard dependency, arbitrary shell execution, network access, paid AI APIs, or private repository dependency

## Sprint 40 Trading Adapter Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 259 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 36 tests`
  - Status: `OK`
- Targeted Sprint 40 tests: Passed
  - Unit: `Ran 7 tests`
  - Integration: `Ran 4 tests`
- Scope:
  - schema v11 migration from v10
  - structured trading request/result contracts
  - fake and paper adapter behavior
  - risk guardrails
  - Executive Planner to Trading Agent to PaperTradingAdapter flow
  - durable events, metrics, persistence, duplicate request protection, CLI smoke, live intent blocking, approval-required blocking, and adapter failure isolation
  - no live KIS, broker credentials, real account access, real orders, automatic trading, automatic approval, MyMoneyGuard dependency, live market data, Telegram trading commands, paid-provider fallback, or unrestricted shell execution

## Sprint 39 Daily Research Pipeline

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 252 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 32 tests`
  - Status: `OK`
- Targeted Sprint 39 tests: Passed
  - Unit: `Ran 6 tests`
  - Integration: `Ran 2 tests`
- Scope:
  - schema v10 migration from v9
  - durable profile/run storage
  - Sprint 38 scheduler integration without a second scheduler
  - deterministic bounded evidence, context, report, pending-review proposal, events, metrics, CLI smoke, duplicate run protection, disabled skip, and failure isolation
  - no Telegram delivery, email, Notion sync, GitHub polling, live market data, Trading Adapter execution, broker/KIS/MyMoneyGuard access, external AI calls, vector DB, automatic approval, shell execution, or plugin execution

## Sprint 38 Scheduler Automation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 246 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 30 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `from gaon.runtime import ScheduledAutomationRunner, ScheduledJobRepository, ScheduledRunStatus`
- CLI smoke: Passed
  - `schedule-create`
  - `schedule-list`
  - `schedule-show`
  - `schedule-run-due`
- Migration tests: Passed
  - schema v8 to v9
- Scope:
  - durable scheduled job management, due execution through Executive Planner and Agent Dispatcher, approval blocking, bounded retry, duplicate run protection, lifecycle events, and metrics
  - no Daily Research business logic, Telegram delivery, live Trading/KIS, automatic approval, paid-provider fallback, or private repository dependency

## Sprint 37 Multi-Agent Execution Framework

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 239 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 27 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `from gaon.runtime import AgentDispatcher, AgentRegistry, AgentRequest, AgentStatus, default_agent_registry`
- CLI smoke: Passed
  - `agent-run --agent research --request`
  - `agent-run --agent coding --request --json`
  - `agent-run --agent memory --request`
- Scope:
  - Agent contracts, registry, dispatcher, deterministic initial agents, capability validation, approval blocking, event emission, and metrics
  - no scheduler execution, daily research automation, Telegram-triggered execution, broker/KIS execution, automatic approval, arbitrary shell execution, or dynamic plugin loading

## Sprint 36 Executive Planner

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 231 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 22 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `executive-plan --request`
  - `executive-plan --request --json`
- Scope:
  - ExecutiveRequest, ExecutivePlan, RoutingDecision, AgentSelection, ToolSelection, and ExecutivePlanner contracts
  - deterministic and provider-backed planning through the existing Provider Registry
  - free-only enforcement and approval-required flag support
  - durable event helper and runtime metrics integration
  - no multi-agent execution, scheduler execution, trading adapter execution, or Telegram integration

## Gaon Phase B v3.0 Research Brain Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 224 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 21 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
  - `status`
  - `metrics`
  - `event-replay-dry-run`
  - `research-plan`
  - `research-run --dry-run`
  - `research-proposals-list`
- Scope:
  - validated research planning
  - safe evidence providers
  - evidence ranking and context building
  - evidence-backed knowledge proposals
  - auditable approval workflow
  - Research Brain v3 orchestration, schema v8, checkpoints, reports, and free-only defaults
  - no live Telegram/OpenAI/Notion/GitHub/Broker/KIS/MyMoneyGuard validation

## Gaon Phase A v2.1 Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 207 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
  - `status`
  - `metrics`
  - `event-replay-dry-run`
- Scope:
  - provider registry and routing
  - explicit plugin lifecycle
  - internal metrics and observability
  - durable event store and replay
  - long-term memory foundation
  - runtime integration
  - no live Telegram/OpenAI/Notion/Broker/VPS validation

## Sprint 18-23 v2 Completion Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 183 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 15 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - approval replay/tamper/cross-scope guards
  - SQLite repository and migration coverage
  - durable queue, scheduler, and recovery coverage
  - controlled runtime loop and CLI smoke coverage
  - security and chaos coverage
  - TradingAdapter contract and fake adapter tests
  - no live Telegram/OpenAI/Notion/Broker verification

## Sprint 17 Production Runtime Service

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 165 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 15 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
- Scope:
  - SQLite schema migration and runtime state store
  - restart offset recovery
  - duplicate processed message guard
  - bounded retry policy
  - health/readiness/db checks
  - backup helper
  - systemd/VPS deployment documentation
  - no real deployment or network smoke

## Sprint 16 Guarded Research Assistant Orchestration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 162 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 14 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - deterministic research proposal creation
  - approval actor/chat/token/expiry checks
  - approval-gated run state machine
  - queue deduplication and retry limits
  - audit event recording
  - no autonomous execution or Learning Memory mutation

## Sprint 15 Guarded Assistant Provider Integration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 158 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 13 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - provider contracts and metadata
  - deterministic fallback provider
  - OpenAI-compatible fake HTTP provider
  - prompt injection separation
  - provider timeout/malformed response fallback
  - provider safety validation
  - no real network calls

## Sprint 14 Memory-Aware Conversation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 152 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 12 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - read-only Learning Memory context builder
  - STRICT/BROAD/GLOBAL retrieval fallback
  - conflict and revalidation warnings
  - confidence used only as ranking signal
  - Telegram memory query fake flow
  - no repository mutation

## Sprint 13 Conversational Assistant Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 148 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 11 tests`
  - Status: `OK`
- Scope:
  - Korean natural-language intent routing
  - Gaon persona responses that address the user as `영하님`
  - deterministic `rule_based` assistant route without LLM dependencies
  - Assistant Provider Protocol boundary for future providers
  - safety warnings for approval, order, and execution-like requests
  - Telegram ordinary text to Conversation Runtime to Telegram response flow
  - no external AI SDK, API key, market data, calendar, stock analysis, or backtest executor connection

## Telegram Production Connection

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 139 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 10 tests`
  - Status: `OK`
- Scope:
  - Telegram Bot API standard-library client
  - fake HTTP success paths for `getMe`, `getUpdates`, and `sendMessage`
  - HTTP 401/429/500, malformed JSON, `ok=false`, timeout, and token masking
  - chat discovery deduplication and preview limiting
  - private text update parsing and ignored update handling
  - allowed chat enforcement, unauthorized no-send behavior, and offset reporting
  - smoke-send fixed message and arbitrary text exclusion
  - production CLI execution gates with dry-run default
  - no real Telegram network call, no shell execution, no GitHub mutation, no broker/trading import

## Gaon Runtime Collaboration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 130 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 6 tests`
  - Status: `OK`
- Scope:
  - runtime configuration and secret masking
  - Windows-safe timezone validation for `UTC` and `Asia/Seoul`
  - invalid boolean/mode/time/weekday rejection
  - explicit CLI dry-run/execute flag behavior
  - event bus duplicate/failure isolation
  - conversation intents and approval safety
  - Telegram dry-run authorization and formatting
  - Notion dry-run mapping and idempotency
  - notification, daily/weekly reports, scheduler, CLI
  - Learning Memory claims snapshot and retrieval modes

## Sprint 12-B

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 119 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - `InMemoryLearningRepository`
  - duplicate and conflict candidate detection
  - chronological lookup and AND filters
  - append-only audit workflow
  - UTC timestamp validation
  - golden JSON and migration fixtures
  - approval scope mismatch guards
  - related-memory retrieval score breakdown
  - repository JSON export/import and v0 migration
  - Research Brain conversion and no-auto-save preparation workflow

## Sprint 12-A

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 94 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - Learning Memory domain contracts added.
  - EvidenceRecord is reused from the existing `gaon.learning.evidence` contract.
  - KnowledgeApproval and PolicyApproval are separate contracts.
  - ConfidenceScore is a review and retrieval signal only and cannot approve knowledge, policy, or preference changes.
  - UserPreference automatic delete and overwrite are blocked.
  - Versioned JSON round-trip and fail-closed schema checks are covered.

## Sprint 11

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 85 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - Gaon Development Contract added.
  - Learning Memory replaces Research Memory terminology for Sprint 11 planning.
  - `gaon.learning` package boundary added.
  - Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts added.
  - ADR and RFC added for Learning Memory core.
  - Research Brain package added with Goal, Plan, Session, Interview, and Journal contracts.
  - Research Brain hardening added session transition guards, terminal completed sessions, pending interview answers, and versioned JSON round-trip.
  - ADR-0003, RFC-0002, and Research Brain guide added.

## Sprint 1

- Unit tests: Passed
  - Command: `PYTHONPATH=src python -m unittest discover -s tests/unit`
  - Result: `Ran 7 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 10

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 69 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
  - Required documentation now includes `docs/architecture/GaonPlatformMasterSpecification.md`
- Gaon Platform specification check: Passed
  - Scope: top-level Gaon Platform master development specification added and linked from README, Master Blueprint, Sprint Roadmap, and release verification.
- Research validation: N/A
- Secret check: Passed

## Sprint 9

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 68 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 8

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 65 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 7

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 64 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 6

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 60 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, or log files were detected.

## Sprint 2

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 25 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.

## Sprint 5

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 54 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 4

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 48 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: Passed
  - Scope: known-scenario deterministic fixture only.
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.

## Sprint 3

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 40 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.
# Sprint 48

Local targeted verification:

- unit tests
- integration tests
- `scripts/verify_release.py`

# Sprint 49

Final local verification:

- full unit tests: PASS, 320 tests
- full integration tests: PASS, 60 tests
- `scripts/verify_release.py`: PASS
- import smoke: PASS
- CLI smoke: PASS, `deployment-status --db :memory:`

# Sprint 50

Final local verification:

- full unit tests: PASS, 320 tests
- full integration tests: PASS, 65 tests
- Sprint 50 E2E tests: PASS
- `scripts/verify_release.py`: PASS
- import smoke: PASS
- CLI smoke: PASS, `v5-release-check`, `v5-status`, and `v5-demo --dry-run`
- migration tests: PASS, v20 to v21 and fresh DB schema v21
- git diff --check: PASS
- security audit: PASS, no `shell=True`, private MyMoneyGuard path hardcoding, subprocess use, or secret markers in new v5 files

# Sprint 50 Hotfix

Final local verification:

- repeated `v5-demo --dry-run` on the same persistent DB: PASS, 3 consecutive runs after `v5-release-check`
- full unit tests: PASS, 320 tests
- full integration tests: PASS, 67 tests
- Sprint 50 E2E tests: PASS, 7 tests
- `scripts/verify_release.py`: PASS
- CLI smoke: PASS, `v5-release-check`, 3 repeated `v5-demo --dry-run`, and `v5-pipeline-history`
- migration tests: PASS via Sprint 50 E2E v20 to v21 and fresh DB schema checks
- git diff --check: PASS

# Sprint 61-70

Final local verification:

- full unit tests: PASS, 398 tests
- full integration tests: PASS, 75 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v28, 9 safe tools
- `llm-agent-release-check`: PASS, plan status completed
- `external-research-release-check`: PASS, SSRF guard and strategy research advisory flow
- `strategy-research-demo`: PASS, recommendation generated without automatic promotion
- `git diff --check`: PASS

# Sprint 71-80

Final local verification:

- full unit tests: PASS, 407 tests
- full integration tests: PASS, 76 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v29, 10 safe tools
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `strategy-research-demo`: PASS
- `quant-research-release-check`: PASS
- `quant-research-demo`: PASS
- deterministic/Telegram/LLM tool regression: PASS
- `git diff --check`: PASS

# Sprint 81-90

Final local verification:

- full unit tests: PASS, 413 tests
- full integration tests: PASS, 77 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v30, 11 safe tools
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `strategy-research-demo`: PASS
- `quant-research-release-check`: PASS
- `quant-research-demo`: PASS
- `feature-discovery-release-check`: PASS
- `feature-discovery-demo`: PASS
- `ai-scientist-release-check`: PASS
- `ai-scientist-demo`: PASS
- `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

# Hotfix 90.1

Final local verification:

- full unit tests: PASS, 422 tests
- full integration tests: PASS, 77 tests
- targeted Telegram/LLM regression: PASS, 29 tests
- `scripts/verify_release.py`: PASS
- `long-response-release-check`: PASS, schema v30, 3 chunks, 1 continuation
- `conversation-release-check`: PASS
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `quant-research-release-check`: PASS
- `feature-discovery-release-check`: PASS
- `ai-scientist-release-check`: PASS
- `git diff --check`: PASS

# Sprint 91-100

Final local verification:

- full unit tests: PASS, 436 tests
- full integration tests: PASS, 80 tests
- targeted self-improving research unit tests: PASS, 13 tests
- targeted self-improving research integration tests: PASS, 3 tests
- `self-improving-research-release-check`: PASS, schema v31
- `conversation-release-check`: PASS
- `llm-agent-release-check`: PASS
- `long-response-release-check`: PASS
- `external-research-release-check`: PASS
- `quant-research-release-check`: PASS
- `feature-discovery-release-check`: PASS
- `ai-scientist-release-check`: PASS
- `scripts/verify_release.py`: PASS
- `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

# Sprint 101-110

Final local verification:

- full unit tests: PASS, 446 tests
- full integration tests: PASS, 83 tests
- targeted real research unit tests: PASS, 10 tests
- targeted real research integration tests: PASS, 3 tests
- `real-research-integration-release-check`: PASS, schema v32
- `conversation-release-check`: PASS
- `llm-agent-release-check`: PASS
- `long-response-release-check`: PASS
- `external-research-release-check`: PASS
- `quant-research-release-check`: PASS
- `feature-discovery-release-check`: PASS
- `ai-scientist-release-check`: PASS
- `self-improving-research-release-check`: PASS
- `scripts/verify_release.py`: PASS
- import smoke: PASS, schema v32
- conflict marker search: PASS
- duplicate definition check: PASS
- `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

# Hotfix 120.3

Targeted verification:

- `tests.unit.test_research_grounding`: PASS
- `tests.integration.test_krx_real_research_pipeline_flow`: PASS
- `strict-real-research-grounding-release-check`: PASS, schema v33

The release check runs with a unique namespace per invocation and verifies that
provider-fabricated metrics such as `trade_count=4`, `MDD=8`, `RSI 20`, and
`volume 1.5x` are not exposed when the structured real research payload records
`trade_count=3`.

# Hotfix 120.4

Targeted verification:

- `tests.unit.test_research_grounding`: PASS
- `tests.integration.test_telegram_conversation_agent`: PASS
- `tests.integration.test_krx_real_research_pipeline_flow`: PASS
- `strict-real-research-grounding-release-check`: PASS, schema v33
- `telegram-strict-real-research-release-check`: PASS, schema v33

The Telegram release check uses the production Korean request text and verifies
the full path from Telegram update to final send. A fake provider attempts to
invent `5.32%`, `1.77%`, `MDD 8`, `거래 횟수 4회`, `RSI(14) 30`, `MA15/MA90`,
and `1.5x`; the final response remains on `tool_read_only_authoritative` and
reports only structured `krx_real_research` values.

# Hotfix 120.5

Targeted verification:

- `tests.unit.test_research_failures`: PASS
- `tests.unit.test_research_grounding`: PASS
- `tests.integration.test_telegram_conversation_agent`: PASS
- `telegram-real-research-failure-routing-release-check`: PASS, schema v33
- `telegram-strict-real-research-release-check`: PASS, schema v33

The failure routing release check verifies market-data unavailable, backtest
failure, actual provider timeout, and unexpected internal exception cases. It
also verifies that authoritative route failures do not call the provider and do
not leak fabricated research metrics.

# Sprint 141-150

Targeted verification:

- `tests.unit.test_multi_symbol_research`: PASS, 6 tests
- `tests.integration.test_multi_symbol_research_flow`: PASS, 2 tests
- `multi-symbol-research-release-check`: PASS, schema v36
- `telegram-multi-symbol-research-release-check`: PASS, schema v36

The release checks verify explicit five-symbol universe handling, stable
strategy and assumption fingerprints, per-symbol evidence, aggregation,
concentration, sample sufficiency, candidate generalization, persistence,
release/demo isolation, and Telegram authoritative routing with
`provider_calls=0`.

# Hotfix 192.1

Final local verification:

- full unit tests: PASS, 811 tests
- full integration tests: PASS, 196 tests
- targeted autonomous learning unit tests: PASS, 36 tests
- targeted external research unit tests: PASS, 51 tests
- `scripts/verify_release.py`: PASS
- `deployment-import-path-check --expected-source .\src\gaon`: PASS
- `gaon-production-real-academic-content-resolution-release-check`: PASS
- `gaon-production-safe-content-acquisition-release-check`: PASS
- `gaon-production-grounded-evidence-release-check`: PASS
- `gaon-production-evidence-backed-hypothesis-release-check`: PASS
- `gaon-production-strategy-experiment-release-check`: PASS
- `gaon-production-authoritative-candidate-validation-release-check`: PASS
- `gaon-production-robustness-ranking-release-check`: PASS
- `gaon-production-human-promotion-gate-release-check`: PASS
- `gaon-production-autonomous-learning-loop-release-check`: PASS
- `gaon-production-external-research-network-release-check`: PASS
- `gaon-production-autonomous-learning-execution-release-check`: PASS
- `gaon-autonomous-learning-e2e-release-check`: PASS
- `gaon-telegram-autonomous-learning-routing-release-check`: PASS
- `gaon-telegram-autonomous-learning-priority-release-check`: PASS
- `gaon-promotion-candidate-presentation-release-check`: PASS
- `research-context-isolation-release-check`: PASS

The new release check verifies DOI/academic metadata resolution into
allowlisted content acquisition, grounded evidence generation, production
fixture-promotion blocking, fingerprint-mismatch blocking, and no strategy or
order mutation. Schema remains v36; no migration was added.

# Hotfix 192.2

Final local verification:

- full unit tests: PASS, 818 tests
- full integration tests: PASS, 196 tests
- targeted autonomous learning/source discovery tests: PASS, 57 tests
- `scripts/verify_release.py`: PASS
- `deployment-import-path-check --expected-source .\src\gaon`: PASS
- `gaon-production-relevant-academic-discovery-release-check`: PASS
- `gaon-production-safe-doi-redirect-release-check`: PASS
- `gaon-production-relevant-academic-content-loop-release-check`: PASS
- `gaon-production-real-academic-content-resolution-release-check`: PASS
- `gaon-production-safe-content-acquisition-release-check`: PASS
- `gaon-production-grounded-evidence-release-check`: PASS
- `gaon-production-evidence-backed-hypothesis-release-check`: PASS
- `gaon-production-strategy-experiment-release-check`: PASS
- `gaon-production-authoritative-candidate-validation-release-check`: PASS
- `gaon-production-robustness-ranking-release-check`: PASS
- `gaon-production-human-promotion-gate-release-check`: PASS
- `gaon-production-autonomous-learning-loop-release-check`: PASS
- `gaon-production-external-research-network-release-check`: PASS
- `gaon-production-autonomous-learning-execution-release-check`: PASS
- `gaon-autonomous-learning-e2e-release-check`: PASS
- `gaon-telegram-autonomous-learning-routing-release-check`: PASS
- `gaon-telegram-autonomous-learning-priority-release-check`: PASS
- `gaon-promotion-candidate-presentation-release-check`: PASS
- `research-context-isolation-release-check`: PASS

The new release checks prove strategy-specific academic query construction,
financial/trading relevance screening, rejection of the production
`Tuple Recovery Strategy` incident before fetch, controlled DOI redirect
resolution through an HTTP intermediate to an approved HTTPS final URL,
content acquisition, normalization, grounded evidence, hypothesis generation,
and candidate experiment creation. Schema remains v36; no migration was added.
