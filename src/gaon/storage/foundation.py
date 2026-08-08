"""Sprint 164 — Gaon Storage Foundation.

Long-lived research/knowledge data is kept outside the source tree.
External content stored here is DATA/EVIDENCE, never executable instruction.

Safety:
- no trading
- no broker/KIS order
- no Champion promotion
- no production strategy mutation
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
from typing import Mapping


STORAGE_SCHEMA_VERSION = 1

DIRECTORIES = (
    "knowledge",
    "knowledge/papers",
    "knowledge/books",
    "knowledge/web",
    "knowledge/reports",
    "knowledge/datasets",
    "evidence",
    "evidence/raw",
    "evidence/normalized",
    "evidence/verified",
    "memory",
    "memory/learning",
    "memory/hypotheses",
    "memory/research_history",
    "experiments",
    "experiments/backtests",
    "experiments/candidates",
    "experiments/rejected",
    "index",
    "cache",
    "archive",
    "logs",
)


def resolve_data_root(
    env: Mapping[str, str] | None = None,
    *,
    system: str | None = None,
) -> Path:
    values = os.environ if env is None else env
    configured = (values.get("GAON_DATA_ROOT") or "").strip()

    if configured:
        return Path(configured).expanduser()

    detected = (system or platform.system()).lower()
    if detected.startswith("win"):
        return Path(r"D:\Gaon")

    return Path("/var/lib/strategylab/gaon-data")


@dataclass(frozen=True)
class GaonStorageLayout:
    root: Path

    def path(self, relative: str) -> Path:
        if relative not in DIRECTORIES:
            raise ValueError(f"unknown Gaon storage path: {relative}")
        return self.root / relative


@dataclass(frozen=True)
class StorageStatus:
    root: str
    exists: bool
    writable: bool
    schema_version: int
    directory_count: int
    total_bytes: int
    free_bytes: int

    def to_json(self) -> dict[str, object]:
        return {
            "root": self.root,
            "exists": self.exists,
            "writable": self.writable,
            "schema_version": self.schema_version,
            "directory_count": self.directory_count,
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
        }


class GaonStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        resolved = Path(root).expanduser() if root is not None else resolve_data_root()
        self.layout = GaonStorageLayout(resolved)

    @property
    def root(self) -> Path:
        return self.layout.root

    def initialize(self) -> StorageStatus:
        self.root.mkdir(parents=True, exist_ok=True)

        for relative in DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)

        marker = self.root / ".gaon-storage.json"
        payload = {
            "schema_version": STORAGE_SCHEMA_VERSION,
            "purpose": "gaon-long-term-research-storage",
            "external_content_policy": "evidence-not-instruction",
            "automatic_trading": False,
            "automatic_champion_promotion": False,
        }

        tmp = self.root / ".gaon-storage.json.tmp"
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, marker)

        return self.status()

    def status(self) -> StorageStatus:
        exists = self.root.exists()
        writable = exists and os.access(self.root, os.W_OK)

        directory_count = 0
        if exists:
            directory_count = sum(
                1 for relative in DIRECTORIES if (self.root / relative).is_dir()
            )

        total_bytes = 0
        free_bytes = 0
        if exists:
            usage = shutil.disk_usage(self.root)
            total_bytes = int(usage.total)
            free_bytes = int(usage.free)

        return StorageStatus(
            root=str(self.root),
            exists=exists,
            writable=writable,
            schema_version=STORAGE_SCHEMA_VERSION,
            directory_count=directory_count,
            total_bytes=total_bytes,
            free_bytes=free_bytes,
        )

    def release_check(self) -> dict[str, object]:
        status = self.initialize()

        marker = self.root / ".gaon-storage.json"
        marker_data = json.loads(marker.read_text(encoding="utf-8"))

        checks = {
            "root_exists": status.exists,
            "writable": status.writable,
            "layout_complete": status.directory_count == len(DIRECTORIES),
            "marker_valid": marker_data.get("schema_version") == STORAGE_SCHEMA_VERSION,
            "external_content_is_evidence": (
                marker_data.get("external_content_policy") == "evidence-not-instruction"
            ),
            "automatic_trading_disabled": marker_data.get("automatic_trading") is False,
            "automatic_champion_promotion_disabled": (
                marker_data.get("automatic_champion_promotion") is False
            ),
        }

        if not all(checks.values()):
            failed = ",".join(name for name, ok in checks.items() if not ok)
            raise RuntimeError(f"Gaon storage release check failed: {failed}")

        return {
            "schema_version": STORAGE_SCHEMA_VERSION,
            "root": str(self.root),
            "directories": status.directory_count,
            "checks": checks,
            "safety": "pass",
        }


def _main() -> int:
    parser = argparse.ArgumentParser(prog="python -m gaon.storage.foundation")
    parser.add_argument(
        "command",
        choices=("init", "status", "release-check"),
    )
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    storage = GaonStorage(args.root)

    if args.command == "init":
        payload = storage.initialize().to_json()
    elif args.command == "status":
        payload = storage.status().to_json()
    else:
        payload = storage.release_check()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "release-check":
        print(
            "gaon-storage-foundation-release-check: PASS "
            f"schema_version={payload['schema_version']} "
            f"root={payload['root']} "
            f"directories={payload['directories']} "
            "external_content=evidence_only "
            "automatic_trading=false "
            "automatic_champion_promotion=false "
            "safety=pass"
        )
    else:
        print(json.dumps(payload, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
