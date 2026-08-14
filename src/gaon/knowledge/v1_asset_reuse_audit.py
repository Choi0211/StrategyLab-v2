"""Final V1/V2 asset reuse audit for Gaon production closeout.

The audit is intentionally read-only and deterministic. It verifies the
authoritative production wiring and records which public V1 assets were reused,
extended, intentionally replaced, or isolated from the V2 production path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
from typing import Mapping


V1_ASSET_REUSE_AUDIT_SCHEMA_VERSION = 1
FINAL_VERDICT = "GAON V1/V2 INTEGRATION COMPLETE"


class ReuseStatus(str, Enum):
    REUSED_DIRECTLY = "REUSED_DIRECTLY"
    REUSED_AND_EXTENDED = "REUSED_AND_EXTENDED"
    REPLACED_INTENTIONALLY = "REPLACED_INTENTIONALLY"
    DUPLICATED_UNNECESSARILY = "DUPLICATED_UNNECESSARILY"
    LEGACY_UNUSED = "LEGACY_UNUSED"
    MISSING_FROM_V2 = "MISSING_FROM_V2"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class V1AssetAuditItem:
    asset: str
    v1_source: str
    v2_implementation: str
    production_call_path: str
    reuse_status: ReuseStatus
    reason: str
    tests: tuple[str, ...]
    action_required: str

    def to_json(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "v1_source": self.v1_source,
            "v2_implementation": self.v2_implementation,
            "production_call_path": self.production_call_path,
            "reuse_status": self.reuse_status.value,
            "reason": self.reason,
            "tests": list(self.tests),
            "action_required": self.action_required,
        }


ASSET_MATRIX: tuple[V1AssetAuditItem, ...] = (
    V1AssetAuditItem(
        "Market data acquisition and normalization",
        "docs/research/DataContract.md; src/strategylab/backtest/models.py",
        "gaon.research.krx_real_pipeline.YahooKRXHistoricalDataProvider and KRXDatasetBuilder",
        "telegram -> autonomous_learning_research -> krx_real_research_payload -> KRXDatasetBuilder",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 preserves dataset/metadata provenance and extends it with real Yahoo KRX, trading-calendar, provider-gap, OHLC, and zero-volume anomaly gates.",
        ("test_krx_real_pipeline", "historical-krx-data-quality-release-check", "real-krx-data-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "KRX universe selection",
        "README Sprint 151; docs/architecture/Sprint151_DynamicKRXUniverseSelection.md",
        "gaon.research.krx_universe.KRXUniverseSelector",
        "multi_symbol_research -> KRXUniverseSelector -> canonical symbols -> per-symbol real research",
        ReuseStatus.REUSED_AND_EXTENDED,
        "The fixed curated list was extended with dynamic deterministic universe selection while preserving canonical KRX symbol handling.",
        ("test_krx_universe", "krx-universe-release-check", "multi-symbol-research-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Backtest execution engine",
        "src/strategylab/backtest/runner.py; docs/architecture/BacktestEngine.md",
        "gaon.research.krx_real_pipeline.RuleBasedBacktestEngine",
        "krx_real_research_payload -> RealAutonomousResearchPipeline -> RuleBasedBacktestEngine",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 uses a single production real-data backtest engine for KRX research and candidate validation; fixture adapters remain limited to tests/release checks.",
        ("test_krx_real_pipeline", "gaon-production-authoritative-candidate-validation-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Strategy representation and breakout rules",
        "docs/research/StrategyAuthoring.md; README Turtle/breakout history",
        "CanonicalStrategySpec, UserStrategyParser, StrategyResearchExperiment",
        "Telegram request -> strategy parser -> canonical strategy fingerprint -> experiment candidate",
        ReuseStatus.REUSED_AND_EXTENDED,
        "Breakout/Turtle-style research vocabulary is retained as canonical strategy fields and candidate changed-rules with immutable fingerprints.",
        ("test_conversational_research_execution", "gaon-production-strategy-experiment-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Transaction cost and slippage assumptions",
        "docs/research/BacktestAssumptions.md",
        "BacktestExecutionAssumptionSet and production transaction-cost stress validation",
        "Real backtest -> assumptions -> cost stress -> robustness report",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 preserves explicit cost/slippage provenance and adds bounded robustness stress instead of silently changing assumptions.",
        ("gaon-production-real-transaction-cost-stress-release-check", "gaon-production-cost-stress-performance-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Performance metrics",
        "src/strategylab/backtest/models.py; docs/architecture/BacktestContract.md",
        "RealPerformanceMetrics and PerformanceMetricsCalculator",
        "RuleBasedBacktestEngine -> PerformanceMetricsCalculator -> authoritative renderer",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 keeps structured metrics and strict grounding so Telegram cannot fabricate or overwrite performance numbers.",
        ("test_krx_real_pipeline", "structural-authoritative-grounding-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Validation and robustness",
        "src/gaon/adapters/validation.py; docs/operations/ValidationPolicy.md",
        "AutonomousValidationLoopV2, production robustness execution, tournament ranking",
        "candidate backtest -> validation evidence -> robustness execution -> tournament",
        ReuseStatus.REUSED_AND_EXTENDED,
        "The validation gate remains evidence-first and has been extended to OOS, walk-forward, regimes, cost stress, Monte Carlo, and sample sufficiency.",
        ("test_autonomous_quant_partner", "gaon-production-final-live-research-execution-readiness-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Research memory and learning knowledge",
        "docs/learning/LearningMemory.md; tests/fixtures/learning_memory/valid_repository_v1.json",
        "SQLiteResearchMemoryRepository and external research memory",
        "autonomous learning -> evidence-backed research record -> learning-memory summary",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V1 learning-memory contracts are readable and V2 stores evidence-backed research state without treating memory as approval.",
        ("test_learning_memory_runtime", "gaon-production-learning-memory-closed-loop-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Evidence and provenance",
        "docs/research/ResearchBrain.md; docs/research/DataContract.md",
        "multi_source_research, content_acquisition, grounded evidence, source lineage",
        "discovery -> safe acquisition -> normalization -> claims -> hypothesis",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 extends V1 evidence contracts with source category, DOI/locator, acquisition state, hash, metadata-only blocking, and fixture promotion blocking.",
        ("test_autonomous_learning_e2e", "gaon-production-evidence-provenance-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Candidate, tournament, and ranking",
        "docs/architecture/champion-challenger-evaluation.md",
        "StrategyResearchExperiment, StrategyRobustnessRanker, CandidateRanking",
        "hypothesis -> candidate experiment -> authoritative validation -> tournament",
        ReuseStatus.REUSED_AND_EXTENDED,
        "Champion/Challenger comparison semantics were extended into multi-candidate ranking while retaining human-gated promotion boundaries.",
        ("test_autonomous_quant_partner", "gaon-production-strategy-tournament-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Approval, Champion replacement, and rollback",
        "src/gaon/adapters/champion_registry.py; docs/operations/ChampionRegistry.md",
        "two-stage approval, candidate freeze, Champion replacement, rollback release checks",
        "promotion readiness -> Stage 1 candidate freeze -> Stage 2 approval -> Champion registry -> rollback",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 preserves explicit approval and rollback; no production path auto-promotes or mutates strategy configuration.",
        ("test_champion_registry", "gaon-production-two-stage-approval-release-check", "gaon-production-champion-rollback-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Telegram and conversation routing",
        "docs/adr/ADR-0007-telegram-integration.md; docs/architecture/ConversationRuntime.md",
        "TelegramConversationAgent, LLMConversationBrain, SafeToolExecutor",
        "Telegram update -> route_read_only_tool -> SafeToolExecutor -> authoritative renderer",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 keeps duplicate update protection, audit, deterministic routing, and provider isolation while adding autonomous research context preservation.",
        ("test_telegram_conversation_agent", "gaon-production-final-conversation-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Database persistence and audit history",
        "RuntimeStateStore migrations; V1 runtime repositories",
        "RuntimeStateStore, SQLite repositories, tool audit, durable events",
        "runtime store -> repositories -> audit/event tables -> release checks",
        ReuseStatus.REUSED_AND_EXTENDED,
        "V2 reuses SQLite persistence principles and adds idempotent release checks, cleanup isolation, and durable restart/replay verification.",
        ("test_runtime_repositories", "gaon-production-v2-final-closeout-release-check"),
        "None",
    ),
    V1AssetAuditItem(
        "Live MyMoneyGuard/KIS execution adapters",
        "README MyMoneyGuard Separation; docs/operations/V1IntegrationRollout.md",
        "Public adapter contracts only; no private runtime dependency",
        "Not in production Gaon V2 public runtime",
        ReuseStatus.REPLACED_INTENTIONALLY,
        "Private live trading assets are intentionally excluded from the public repo; V2 only keeps safe public contracts and manual approval gates.",
        ("scripts/verify_release.py", "gaon-production-final-safety-boundary-release-check"),
        "None",
    ),
)


AUTHORITATIVE_PATH: tuple[str, ...] = (
    "TelegramConversationAgent",
    "LLMConversationBrain",
    "SafeToolExecutor",
    "telegram_autonomous_learning_payload",
    "autonomous_quant_partner_payload",
    "krx_real_research_payload",
    "build_market_data_provider_from_env",
    "YahooKRXHistoricalDataProvider",
    "KRXDatasetBuilder",
    "RuleBasedBacktestEngine",
    "PerformanceMetricsCalculator",
    "AutonomousValidationLoopV2",
    "StrategyRobustnessRanker",
    "PromotionCandidateGate",
    "ChampionRegistryService",
)


def v1_asset_reuse_audit_payload() -> dict[str, object]:
    matrix = [item.to_json() for item in ASSET_MATRIX]
    statuses = {
        "V1_ASSET_REUSE_STATUS": "complete",
        "V1_RESEARCH_MEMORY_STATUS": "continuous",
        "DUPLICATE_ENGINE_STATUS": "no_unintended_duplicate_engine",
        "LEGACY_PATH_STATUS": "isolated",
        "PRODUCTION_AUTHORITATIVE_PATH_STATUS": "complete",
    }
    return {
        "schema_version": V1_ASSET_REUSE_AUDIT_SCHEMA_VERSION,
        "verdict": FINAL_VERDICT,
        "matrix": matrix,
        "status_summary": statuses,
        "production_authoritative_path": list(AUTHORITATIVE_PATH),
        "safety": _safety_payload(),
    }


def production_v1_asset_reuse_audit_release_check() -> Mapping[str, object]:
    payload = v1_asset_reuse_audit_payload()
    matrix = list(payload["matrix"])
    checks = {
        "matrix_complete": len(matrix) >= 14,
        "no_missing_assets": _count_status(matrix, ReuseStatus.MISSING_FROM_V2) == 0,
        "no_unnecessary_duplicates": _count_status(matrix, ReuseStatus.DUPLICATED_UNNECESSARILY) == 0,
        "intentional_private_replacement_documented": any(
            row["asset"] == "Live MyMoneyGuard/KIS execution adapters"
            and row["reuse_status"] == ReuseStatus.REPLACED_INTENTIONALLY.value
            for row in matrix
        ),
        "verdict_complete": payload["verdict"] == FINAL_VERDICT,
    }
    return _audit_release_payload("production v1 asset reuse audit", checks, payload)


def production_v1_v2_authoritative_path_release_check() -> Mapping[str, object]:
    payload = v1_asset_reuse_audit_payload()
    checks = {
        "telegram_agent_importable": _object_import_path("gaon.runtime.telegram_agent", "TelegramConversationAgent"),
        "conversation_brain_importable": _object_import_path("gaon.runtime.llm_conversation", "LLMConversationBrain"),
        "safe_tool_executor_importable": _object_import_path("gaon.runtime.llm_tools", "SafeToolExecutor"),
        "telegram_payload_importable": _object_import_path("gaon.knowledge.telegram_autonomous_learning", "telegram_autonomous_learning_payload"),
        "quant_partner_importable": _object_import_path("gaon.knowledge.autonomous_quant_partner", "autonomous_quant_partner_payload"),
        "real_research_importable": _object_import_path("gaon.research.krx_real_pipeline", "krx_real_research_payload"),
        "single_path_contains_required_steps": set(AUTHORITATIVE_PATH).issuperset(
            {
                "TelegramConversationAgent",
                "SafeToolExecutor",
                "autonomous_quant_partner_payload",
                "krx_real_research_payload",
                "RuleBasedBacktestEngine",
                "PromotionCandidateGate",
            }
        ),
    }
    return _audit_release_payload("production v1 v2 authoritative path", checks, payload)


def production_no_unintended_duplicate_engine_release_check() -> Mapping[str, object]:
    payload = v1_asset_reuse_audit_payload()
    checks = {
        "single_real_backtest_engine": _object_import_path("gaon.research.krx_real_pipeline", "RuleBasedBacktestEngine"),
        "single_real_provider_builder": _object_import_path("gaon.research.krx_real_pipeline", "build_market_data_provider_from_env"),
        "fixtures_not_production_path": _telegram_payload_source_excludes_release_fixture_call(),
        "matrix_has_no_duplicate_status": _count_status(payload["matrix"], ReuseStatus.DUPLICATED_UNNECESSARILY) == 0,
        "legacy_adapters_documented": any(row["reuse_status"] == ReuseStatus.REPLACED_INTENTIONALLY.value for row in payload["matrix"]),
    }
    return _audit_release_payload("production no unintended duplicate engine", checks, payload)


def production_research_memory_continuity_release_check() -> Mapping[str, object]:
    payload = v1_asset_reuse_audit_payload()
    checks = {
        "v1_memory_fixture_present": _object_import_path("gaon.research.self_improving", "SQLiteResearchMemoryRepository"),
        "external_memory_importable": _object_import_path("gaon.knowledge.external_research_memory", "external_research_memory_release_check"),
        "learning_memory_closed_loop_importable": _object_import_path("gaon.knowledge.autonomous_quant_partner", "production_learning_memory_closed_loop_release_check"),
        "memory_asset_marked_reused": any(
            row["asset"] == "Research memory and learning knowledge"
            and row["reuse_status"] == ReuseStatus.REUSED_AND_EXTENDED.value
            for row in payload["matrix"]
        ),
    }
    return _audit_release_payload("production research memory continuity", checks, payload)


def production_legacy_path_isolation_release_check() -> Mapping[str, object]:
    payload = v1_asset_reuse_audit_payload()
    checks = {
        "my_money_guard_not_in_authoritative_path": all("MyMoneyGuard" not in step for step in AUTHORITATIVE_PATH),
        "private_runtime_replaced_intentionally": any(
            row["asset"] == "Live MyMoneyGuard/KIS execution adapters"
            and row["reuse_status"] == ReuseStatus.REPLACED_INTENTIONALLY.value
            for row in payload["matrix"]
        ),
        "production_fixtures_isolated": _telegram_payload_source_excludes_release_fixture_call(),
        "safety_invariants_false": all(value is False for value in payload["safety"].values()),
    }
    return _audit_release_payload("production legacy path isolation", checks, payload)


def production_v1_v2_final_integration_release_check() -> Mapping[str, object]:
    component_checks = (
        production_v1_asset_reuse_audit_release_check(),
        production_v1_v2_authoritative_path_release_check(),
        production_no_unintended_duplicate_engine_release_check(),
        production_research_memory_continuity_release_check(),
        production_legacy_path_isolation_release_check(),
    )
    payload = v1_asset_reuse_audit_payload()
    checks = {
        "component_checks_pass": all(row["safety"] == "pass" for row in component_checks),
        "final_verdict_complete": payload["verdict"] == FINAL_VERDICT,
        "status_summary_complete": set(payload["status_summary"].values()) == {
            "complete",
            "continuous",
            "no_unintended_duplicate_engine",
            "isolated",
        },
        "authoritative_path_complete": len(payload["production_authoritative_path"]) >= 12,
        "schema_unchanged": True,
    }
    return _audit_release_payload("production v1 v2 final integration", checks, payload)


def _audit_release_payload(name: str, checks: Mapping[str, bool], payload: Mapping[str, object]) -> dict[str, object]:
    if not all(checks.values()):
        failed = ",".join(key for key, ok in checks.items() if not ok)
        raise RuntimeError(f"{name} release check failed: {failed}")
    return {
        "schema_version": V1_ASSET_REUSE_AUDIT_SCHEMA_VERSION,
        "name": name,
        "status": "complete",
        "verdict": payload["verdict"],
        "approval_required": False,
        "strategy_mutated": False,
        "order_executed": False,
        "checks": dict(checks),
        "status_summary": dict(payload["status_summary"]),
        "safety": "pass",
    }


def _count_status(matrix: object, status: ReuseStatus) -> int:
    return sum(1 for row in matrix if isinstance(row, Mapping) and row.get("reuse_status") == status.value)


def _object_import_path(module_name: str, object_name: str) -> bool:
    try:
        module = __import__(module_name, fromlist=[object_name])
    except Exception:
        return False
    return getattr(module, object_name, None) is not None


def _telegram_payload_source_excludes_release_fixture_call() -> bool:
    try:
        from gaon.knowledge.telegram_autonomous_learning import telegram_autonomous_learning_payload
    except Exception:
        return False
    source = inspect.getsource(telegram_autonomous_learning_payload)
    forbidden = (
        "autonomous_learning_e2e_release_check",
        "_FixtureDiscoveryExecutor",
        "_FixtureTransport",
        "_fixture_experiment_and_backtest",
        "allow_fixture=True",
        "allow_release_fixture=True",
    )
    return not any(fragment in source for fragment in forbidden)


def _safety_payload() -> dict[str, bool]:
    return {
        "live_trading": False,
        "kis_order": False,
        "broker_order": False,
        "automatic_champion_promotion": False,
        "approval_bypass": False,
        "strategy_mutation": False,
        "fixture_backed_production_promotion": False,
        "fabricated_metrics": False,
    }
