"""StrategyLab v2 release verification."""

from __future__ import annotations

import subprocess
import sys
import os
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _test_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(root / "src"), str(root / "tests" / "unit"), str(root / "tests" / "integration"), str(root / "tests" / "fixtures")]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _verify(report) -> int:
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
            encoding="utf-8",
            errors="replace",
        )
        summary = re.search(r"Ran (\d+) tests?", tests.stderr)
        failures = re.search(r"failures=(\d+)", tests.stderr)
        errors = re.search(r"errors=(\d+)", tests.stderr)
        skipped = re.search(r"skipped=(\d+)", tests.stderr)
        report["suites"][name] = {"passed": tests.returncode == 0,
            "executed": int(summary[1]) if summary else 0,
            "skipped": int(skipped[1]) if skipped else 0,
            "failures": int(failures[1]) if failures else 0,
            "errors": int(errors[1]) if errors else 0}
        print(name + ": " + json.dumps(report["suites"][name]))
        if summary is None or int(summary[1]) == 0:
            return 1
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
        encoding="utf-8",
        errors="replace",
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
        "docs/architecture/LLMAgent.md",
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
        "docs/operations/LLMAgent.md",
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


def main(report_json=None) -> int:
    report = {"schema_version": 1, "status": "failed", "suites": {},
              "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        report["sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        report["source_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        code = _verify(report)
        report["status"] = "passed" if code == 0 else "failed"
        return code
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if report_json:
            path = Path(report_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-json")
    raise SystemExit(main(parser.parse_args().report_json))
