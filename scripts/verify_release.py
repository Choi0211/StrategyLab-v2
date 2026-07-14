"""StrategyLab v2 release verification."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


def _test_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(root / "src"), str(root / "tests" / "unit"), str(root / "tests" / "integration")]
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
    required = [
        "docs/architecture/MasterBlueprint.md",
        "docs/architecture/SprintRoadmap.md",
        "docs/tests/TestResults.md",
        "docs/releases/ReleaseNotes.md",
        "docs/releases/CHANGELOG.md",
        "docs/operations/Runbook.md",
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
    print("Required files: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
