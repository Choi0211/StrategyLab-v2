#!/usr/bin/env python3
"""VPS-side storage lifecycle manager for StrategyLab-v2 (and, optionally,
a sibling Binance deployment).

Pure standard library, no new dependency, matching this codebase's minimal
external-dependency philosophy.

Classifies on-disk data into three tiers:

  HOT  - the live database file(s) and current code/config. Never touched,
         moved, or deleted by this script under any mode.
  WARM - recent research evidence / backtest / market-data caches, i.e.
         anything under a directory named "research_cache" (configurable
         via --warm-dir-name) that is younger than --warm-days (default 14).
  COLD - the upgrade script's DB backups directory (deploy/scripts/
         upgrade_service.sh writes timestamped backups under
         <var-dir>/backups/), plus anything under a WARM-shaped directory
         that is OLDER than --warm-days, plus anything under a directory
         named "research_exports" (configurable via --cold-dir-name)
         regardless of age.

Modes (mutually exclusive, pick exactly one):

  --report                         (default) Read-only. Prints a JSON
                                    summary of bytes per tier and overall
                                    filesystem usage, with warning flags at
                                    the 70%/80%/90% thresholds (configurable
                                    via --warn-at). Never modifies anything.
                                    Safe to run at any time, e.g. from a
                                    daily systemd timer.

  --build-cold-manifest PATH       Read-only w.r.t. the classified files
                                    (it opens each COLD file to hash it, but
                                    never modifies/moves/deletes anything).
                                    Writes a JSON manifest to PATH describing
                                    every COLD-tier file: path, size, and a
                                    SHA-256 hash. This is the exact contract
                                    a PC-side "Archive Sync Client" (built
                                    separately, not by this script) is
                                    expected to consume: it downloads every
                                    listed file, verifies each SHA-256
                                    locally, and - only for files it has
                                    positively verified - writes its OWN
                                    "verified manifest" (identical schema)
                                    that can later be fed to --cleanup.

  --cleanup VERIFIED_MANIFEST_PATH Destructive, but conservative. Reads a
                                    verified-manifest JSON (produced by the
                                    PC-side archive client, same schema as
                                    --build-cold-manifest's output) and
                                    deletes ONLY files that are ALL of:
                                    (a) currently classified as COLD tier,
                                    (b) listed in the verified manifest, and
                                    (c) whose CURRENT on-disk SHA-256 still
                                    matches the hash recorded in the
                                    verified manifest (i.e. the file has not
                                    changed since it was verified as safely
                                    archived). Anything that fails any of
                                    these three checks is left alone and
                                    logged as skipped, never deleted. Every
                                    deletion (and every skip) is appended to
                                    a JSON-lines deletion log next to the
                                    verified manifest (or at --deletion-log
                                    if given) - nothing is deleted silently.

Manifest JSON schema (produced by --build-cold-manifest, and the schema the
PC-side client's own "verified manifest" output must also follow so
--cleanup can consume it):

    {
      "schema_version": 1,
      "generated_at": "2026-08-23T00:00:00+00:00",
      "root_paths": ["/var/lib/strategylab", "/opt/binance-trading"],
      "files": [
        {
          "path": "/var/lib/strategylab/backups/gaon-runtime.sqlite.2026-08-01T000000.bak",
          "size_bytes": 1048576,
          "sha256": "3b5d5c3712955042212316173ccf37be5f7b448..."
        }
      ]
    }

--build-cold-manifest always writes exactly this shape. --cleanup expects
its VERIFIED_MANIFEST_PATH argument to be this same shape (a "files" list
of {path, size_bytes, sha256} objects) - the PC-side client is responsible
for only including entries it has itself verified, since --cleanup trusts
the manifest's sha256 field as "this is what the PC verified", not as
something it re-derives from anywhere else.

This script never auto-triggers destructive action based on disk
thresholds - --report only ever reports/warns. Deciding what to do about a
90%-full disk (run --cleanup sooner, expand storage, etc.) is left to a
human operator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_WARM_DAYS = 14
DEFAULT_WARM_DIR_NAME = "research_cache"
DEFAULT_COLD_DIR_NAME = "research_exports"
DEFAULT_BACKUPS_DIR_NAME = "backups"
DEFAULT_WARN_THRESHOLDS = (70, 80, 90)
HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ClassifiedFile:
    path: Path
    size_bytes: int
    tier: str  # "hot" | "warm" | "cold"


@dataclass
class ClassificationResult:
    files: list[ClassifiedFile] = field(default_factory=list)

    def bytes_for(self, tier: str) -> int:
        return sum(f.size_bytes for f in self.files if f.tier == tier)


def _iter_files(root: Path):
    if not root.exists():
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            yield Path(dirpath) / name


def _is_under_dir_named(path: Path, root: Path, dir_name: str) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return dir_name in rel_parts[:-1]  # dir_name must be an ancestor dir, not the file itself


def classify(root_paths: list[Path], *, warm_days: int, warm_dir_name: str, cold_dir_name: str, backups_dir_name: str) -> ClassificationResult:
    """HOT is the default tier for anything not matched by a WARM/COLD rule
    below - i.e. current code, current config, and the live DB file(s) all
    fall through to HOT untouched, which is the safe default."""
    result = ClassificationResult()
    now = time.time()
    warm_cutoff_seconds = warm_days * 86400

    for root in root_paths:
        for path in _iter_files(root):
            try:
                stat = path.stat()
            except OSError:
                continue
            size_bytes = stat.st_size
            age_seconds = now - stat.st_mtime

            in_backups_dir = _is_under_dir_named(path, root, backups_dir_name)
            in_cold_named_dir = _is_under_dir_named(path, root, cold_dir_name)
            in_warm_named_dir = _is_under_dir_named(path, root, warm_dir_name)

            if in_backups_dir or in_cold_named_dir:
                tier = "cold"
            elif in_warm_named_dir:
                tier = "cold" if age_seconds > warm_cutoff_seconds else "warm"
            else:
                tier = "hot"

            result.files.append(ClassifiedFile(path=path, size_bytes=size_bytes, tier=tier))
    return result


def _disk_usage_for(root_paths: list[Path]) -> dict[str, object]:
    """Reports usage per distinct filesystem among the given roots (multiple
    root paths commonly share one filesystem on a single VPS, so this
    de-duplicates by resolved mount rather than double-counting)."""
    seen: dict[str, dict[str, object]] = {}
    for root in root_paths:
        probe = root if root.exists() else root.parent
        if not probe.exists():
            continue
        usage = shutil.disk_usage(probe)
        key = str(probe.resolve())
        seen.setdefault(key, {
            "probed_path": str(root),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        })
    return seen


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def cmd_report(args: argparse.Namespace) -> int:
    root_paths = [Path(p) for p in args.root]
    classification = classify(
        root_paths, warm_days=args.warm_days, warm_dir_name=args.warm_dir_name,
        cold_dir_name=args.cold_dir_name, backups_dir_name=args.backups_dir_name,
    )
    disk = _disk_usage_for(root_paths)
    warnings = []
    for fs_key, fs_info in disk.items():
        used_pct = fs_info["used_pct"]
        crossed = [t for t in sorted(args.warn_at) if used_pct >= t]
        if crossed:
            warnings.append({
                "filesystem": fs_key, "used_pct": used_pct,
                "crossed_thresholds_pct": crossed,
                "message": f"disk usage at {used_pct}% for {fs_info['probed_path']} "
                           f"(crossed {max(crossed)}% threshold) - report only, no action taken automatically",
            })
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "root_paths": [str(p) for p in root_paths],
        "tier_bytes": {
            "hot": classification.bytes_for("hot"),
            "warm": classification.bytes_for("warm"),
            "cold": classification.bytes_for("cold"),
        },
        "file_counts": {
            "hot": sum(1 for f in classification.files if f.tier == "hot"),
            "warm": sum(1 for f in classification.files if f.tier == "warm"),
            "cold": sum(1 for f in classification.files if f.tier == "cold"),
        },
        "disk_usage": disk,
        "warnings": warnings,
        "destructive_action_taken": False,
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_build_cold_manifest(args: argparse.Namespace) -> int:
    root_paths = [Path(p) for p in args.root]
    classification = classify(
        root_paths, warm_days=args.warm_days, warm_dir_name=args.warm_dir_name,
        cold_dir_name=args.cold_dir_name, backups_dir_name=args.backups_dir_name,
    )
    cold_files = [f for f in classification.files if f.tier == "cold"]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "root_paths": [str(p) for p in root_paths],
        "files": [
            {"path": str(f.path), "size_bytes": f.size_bytes, "sha256": _sha256_of(f.path)}
            for f in cold_files
        ],
    }
    out_path = Path(args.build_cold_manifest)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    tmp_path.replace(out_path)
    print(f"cold manifest written: {out_path} ({len(manifest['files'])} files)")
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    root_paths = [Path(p) for p in args.root]
    classification = classify(
        root_paths, warm_days=args.warm_days, warm_dir_name=args.warm_dir_name,
        cold_dir_name=args.cold_dir_name, backups_dir_name=args.backups_dir_name,
    )
    cold_paths = {str(f.path): f for f in classification.files if f.tier == "cold"}

    with open(args.cleanup, encoding="utf-8") as handle:
        verified_manifest = json.load(handle)
    verified_by_path = {entry["path"]: entry for entry in verified_manifest.get("files", [])}

    deletion_log_path = Path(args.deletion_log) if args.deletion_log else Path(args.cleanup).with_suffix(".deletion-log.jsonl")
    deleted = []
    skipped = []

    with open(deletion_log_path, "a", encoding="utf-8") as log_handle:
        for path_str, cold_file in cold_paths.items():
            verified_entry = verified_by_path.get(path_str)
            if verified_entry is None:
                skipped.append({"path": path_str, "reason": "not_in_verified_manifest"})
                continue
            try:
                current_hash = _sha256_of(cold_file.path)
            except OSError as exc:
                skipped.append({"path": path_str, "reason": f"unreadable: {exc}"})
                continue
            if current_hash != verified_entry.get("sha256"):
                skipped.append({"path": path_str, "reason": "hash_mismatch_since_verification"})
                continue

            log_handle.write(json.dumps({
                "action": "delete", "path": path_str, "size_bytes": cold_file.size_bytes,
                "sha256": current_hash, "verified_manifest": str(args.cleanup), "at": _utc_now(),
            }) + "\n")
            if not args.dry_run:
                cold_file.path.unlink()
            deleted.append(path_str)

        for path_str, reason in [(s["path"], s["reason"]) for s in skipped]:
            log_handle.write(json.dumps({"action": "skip", "path": path_str, "reason": reason, "at": _utc_now()}) + "\n")

    result = {
        "schema_version": SCHEMA_VERSION, "generated_at": _utc_now(), "dry_run": args.dry_run,
        "deleted_count": len(deleted), "skipped_count": len(skipped),
        "deletion_log": str(deletion_log_path),
        "destructive_action_taken": bool(deleted) and not args.dry_run,
    }
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=None,
                         help="Root path to scan; may be given multiple times. "
                              "Defaults to /var/lib/strategylab, /opt/strategylab-v2, "
                              "and /opt/binance-trading (only those that exist).")
    parser.add_argument("--warm-days", type=int, default=DEFAULT_WARM_DAYS)
    parser.add_argument("--warm-dir-name", default=DEFAULT_WARM_DIR_NAME)
    parser.add_argument("--cold-dir-name", default=DEFAULT_COLD_DIR_NAME)
    parser.add_argument("--backups-dir-name", default=DEFAULT_BACKUPS_DIR_NAME)
    parser.add_argument("--warn-at", type=int, action="append", default=None,
                         help="Disk-usage percent threshold(s) to flag in --report output; "
                              "may be given multiple times. Defaults to 70, 80, 90.")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="Default mode: read-only summary.")
    mode.add_argument("--build-cold-manifest", metavar="PATH", default=None)
    mode.add_argument("--cleanup", metavar="VERIFIED_MANIFEST_PATH", default=None)

    parser.add_argument("--deletion-log", default=None,
                         help="Only used with --cleanup. Defaults to <verified-manifest>.deletion-log.jsonl")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only used with --cleanup. Logs what WOULD be deleted without deleting anything.")
    return parser


def _default_roots() -> list[str]:
    candidates = ["/var/lib/strategylab", "/opt/strategylab-v2", "/opt/binance-trading"]
    return [c for c in candidates if os.path.exists(c)] or candidates[:2]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.root is None:
        args.root = _default_roots()
    if args.warn_at is None:
        args.warn_at = list(DEFAULT_WARN_THRESHOLDS)

    if args.build_cold_manifest:
        return cmd_build_cold_manifest(args)
    if args.cleanup:
        return cmd_cleanup(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
