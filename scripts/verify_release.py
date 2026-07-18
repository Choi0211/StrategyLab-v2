"""StrategyLab v2 release verification."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


def _test_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(root / "src"), str(root / "tests" / "unit"), str(root / "tests" / "integration"), str(root / "tests" / "fixtures")]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = _test_env(root)
    test_suites = (("unit", "tests/unit"), ("integration", "tests/integration"))
    for name, path in test_suites:
        tests = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", path],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )
        if tests.returncode != 0:
            print(f"{name} tests failed")
            print(tests.stdout)
            print(tests.stderr)
            return tests.returncode
    cli = subprocess.run(
        [sys.executable, "-m", "gaon.runtime.cli", "v5-status", "--db", ":memory:"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
    )
    if cli.returncode != 0:
        print("CLI importability check failed")
        print(cli.stdout)
        print(cli.stderr)
        return cli.returncode
    required = [
        "docs/architecture/GaonPlatformMasterSpecification.md",
        "docs/architecture/GaonDevelopmentContract.md",
        "docs/architecture/MasterBlueprint.md",
        "docs/architecture/Sprint11_Brief.md",
        "docs/architecture/Sprint12_Brief.md",
        "docs/architecture/LearningMemoryArchitecture.md",
        "docs/architecture/GaonRuntimeArchitecture.md",
        "docs/architecture/ConversationRuntime.md",
        "docs/architecture/LLMBrain.md",
        "docs/architecture/CollaborationIntegrations.md",
        "docs/architecture/SprintRoadmap.md",
        "docs/adr/ADR-0001-learning-memory-core.md",
        "docs/adr/ADR-0003-research-brain-contracts.md",
        "docs/adr/ADR-0004-learning-memory-storage.md",
        "docs/adr/ADR-0005-knowledge-lifecycle.md",
        "docs/adr/ADR-0006-runtime-event-bus.md",
        "docs/adr/ADR-0007-telegram-integration.md",
        "docs/adr/ADR-0008-notion-sync.md",
        "docs/adr/ADR-0009-report-scheduler.md",
        "docs/rfc/RFC-0001-sprint11-learning-engine.md",
        "docs/rfc/RFC-0002-sprint11-research-brain.md",
        "docs/rfc/RFC-0003-sprint12-learning-memory.md",
        "docs/rfc/RFC-0004-gaon-runtime-collaboration.md",
        "docs/research/ResearchBrain.md",
        "docs/tests/Sprint12_TestPlan.md",
        "docs/learning/LearningMemory.md",
        "docs/conversation/ConversationEngine.md",
        "docs/tests/TestResults.md",
        "docs/releases/ReleaseNotes.md",
        "docs/releases/CHANGELOG.md",
        "docs/operations/Runbook.md",
        "docs/operations/RuntimeConfiguration.md",
        "docs/operations/TelegramSetup.md",
        "docs/operations/LLMBrain.md",
        "docs/operations/NotionSetup.md",
        "docs/operations/DailyWeeklyJobs.md",
        "docs/architecture/strategy-handoff.md",
        "docs/architecture/strategy-deployment-workflow.md",
        "docs/operations/StrategyHandoff.md",
        "docs/operations/StrategyDeployment.md",
        "docs/releases/gaon-v5.0-rc.md",
        "docs/tests/GaonRuntime_TestPlan.md",
        "tests/fixtures/learning_memory/valid_repository_v1.json",
        "tests/fixtures/learning_memory/legacy_repository_v0.json",
        "tests/fixtures/learning_memory/unsupported_repository_v2.json",
        "tests/fixtures/learning_memory/duplicate_record_ids.json",
        "tests/fixtures/learning_memory/invalid_timestamp.json",
        "tests/fixtures/learning_memory/missing_evidence.json",
        "tests/fixtures/learning_memory/malformed_repository.json",
        "tests/fixtures/learning_memory/related_memory_ranking.json",
    ]
    missing = [path for path in required if not (root / path).exists()]
    if missing:
        print("Missing required files:")
        for path in missing:
            print(f"- {path}")
        return 1
    print("StrategyLab v2 release verification passed.")
    print("Unit tests: PASS")
    print("Integration tests: PASS")
    print("CLI importability: PASS")
    print("Required files: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
