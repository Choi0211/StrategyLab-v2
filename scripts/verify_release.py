"""StrategyLab v2 release verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit"],
        cwd=root,
        env={**dict(PYTHONPATH="src;tests/unit")},
        text=True,
        capture_output=True,
    )
    if tests.returncode != 0:
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
    print("Required files: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

