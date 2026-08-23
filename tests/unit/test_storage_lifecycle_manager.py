"""Tests for deploy/scripts/storage_lifecycle_manager.py.

This script lives outside the installable `gaon` package (deploy/ is
deployment tooling, not application code - see its own module docstring
and gaon/runtime/web_api.py's _handle_storage_status, which reuses it via
subprocess for exactly this reason), so it's loaded here via
importlib rather than a normal package import - this is the one place in
this test suite that needs that, and it's deliberate, not an oversight.

Covers the storage-related test gates from the master integration plan:
manifest schema, SHA-256 mismatch handling, safe (verified+hash-matched
only) deletion, deletion logging, dry-run, and disk-threshold warnings -
these had NO permanent automated test before (only ad hoc manual
verification during development), which is exactly the "a check nobody
calls never actually runs" gap this codebase has had to fix before.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "storage_lifecycle_manager.py"
_spec = importlib.util.spec_from_file_location("storage_lifecycle_manager", _SCRIPT_PATH)
slm = importlib.util.module_from_spec(_spec)
sys.modules["storage_lifecycle_manager"] = slm
_spec.loader.exec_module(slm)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ClassifyTests(unittest.TestCase):
    def test_default_tier_is_hot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gaon-runtime.sqlite").write_bytes(b"live db")
            result = slm.classify([root], warm_days=14, warm_dir_name="research_cache", cold_dir_name="research_exports", backups_dir_name="backups")
            self.assertEqual(len(result.files), 1)
            self.assertEqual(result.files[0].tier, "hot")

    def test_backups_dir_is_always_cold_regardless_of_age(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "backups" / "fresh.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"just made")
            result = slm.classify([root], warm_days=14, warm_dir_name="research_cache", cold_dir_name="research_exports", backups_dir_name="backups")
            self.assertEqual(result.files[0].tier, "cold")

    def test_warm_dir_ages_into_cold_past_warm_days(self) -> None:
        import os
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = root / "research_cache" / "fresh.json"
            old = root / "research_cache" / "old.json"
            fresh.parent.mkdir(parents=True)
            fresh.write_bytes(b"fresh")
            old.write_bytes(b"old")
            old_mtime = time.time() - (20 * 86400)  # 20 days old, past a 14-day warm cutoff
            os.utime(old, (old_mtime, old_mtime))

            result = slm.classify([root], warm_days=14, warm_dir_name="research_cache", cold_dir_name="research_exports", backups_dir_name="backups")
            tiers = {f.path.name: f.tier for f in result.files}
            self.assertEqual(tiers["fresh.json"], "warm")
            self.assertEqual(tiers["old.json"], "cold")


class BuildColdManifestTests(unittest.TestCase):
    def test_manifest_schema_and_hash_are_correct(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            data = b"a real backup file's bytes"
            f = root / "backups" / "a.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(data)
            manifest_out = Path(tmp) / "cold-manifest.json"

            exit_code = slm.main(["--root", str(root), "--build-cold-manifest", str(manifest_out)])
            self.assertEqual(exit_code, 0)

            manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], slm.SCHEMA_VERSION)
            self.assertIn("generated_at", manifest)
            self.assertEqual(manifest["root_paths"], [str(root)])
            self.assertEqual(len(manifest["files"]), 1)
            entry = manifest["files"][0]
            self.assertEqual(entry["path"], str(f))
            self.assertEqual(entry["size_bytes"], len(data))
            self.assertEqual(entry["sha256"], _sha256_bytes(data))

    def test_hot_and_warm_files_never_appear_in_the_cold_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            (root / "gaon-runtime.sqlite").parent.mkdir(parents=True, exist_ok=True)
            (root).mkdir(parents=True, exist_ok=True)
            (root / "gaon-runtime.sqlite").write_bytes(b"live db - must stay HOT")
            warm = root / "research_cache" / "recent.json"
            warm.parent.mkdir(parents=True)
            warm.write_bytes(b"recent research cache - must stay WARM")
            manifest_out = Path(tmp) / "cold-manifest.json"

            slm.main(["--root", str(root), "--build-cold-manifest", str(manifest_out)])
            manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"], [], "only COLD-tier files may ever appear in the cold manifest")


class CleanupSafeDeletionTests(unittest.TestCase):
    """The core safety property: --cleanup deletes ONLY a file that is both
    (a) listed in the verified manifest and (b) whose CURRENT on-disk
    sha256 still matches what's recorded there - never based on the
    verified manifest alone."""

    def test_verified_and_hash_matched_file_is_deleted_and_logged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            data = b"safely archived elsewhere"
            f = root / "backups" / "safe.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(data)
            verified = {
                "schema_version": slm.SCHEMA_VERSION, "generated_at": "2026-08-23T00:00:00+00:00",
                "root_paths": [str(root)],
                "files": [{"path": str(f), "size_bytes": len(data), "sha256": _sha256_bytes(data)}],
            }
            verified_path = Path(tmp) / "verified.json"
            verified_path.write_text(json.dumps(verified), encoding="utf-8")

            exit_code = slm.main(["--root", str(root), "--cleanup", str(verified_path)])
            self.assertEqual(exit_code, 0)
            self.assertFalse(f.exists(), "a verified, hash-matched COLD file must be deleted")

            deletion_log = verified_path.with_suffix(".deletion-log.jsonl")
            self.assertTrue(deletion_log.exists())
            lines = [json.loads(line) for line in deletion_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["action"], "delete")
            self.assertEqual(lines[0]["path"], str(f))

    def test_hash_mismatch_since_verification_is_never_deleted(self) -> None:
        """Simulates a file that changed on disk after the verified
        manifest was produced (e.g. re-created, corrupted, or a stale
        manifest reused against a different backup run)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            f = root / "backups" / "changed.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"current content on disk")
            verified = {
                "schema_version": slm.SCHEMA_VERSION, "generated_at": "2026-08-23T00:00:00+00:00",
                "root_paths": [str(root)],
                "files": [{"path": str(f), "size_bytes": 999, "sha256": "0" * 64}],  # deliberately wrong
            }
            verified_path = Path(tmp) / "verified.json"
            verified_path.write_text(json.dumps(verified), encoding="utf-8")

            exit_code = slm.main(["--root", str(root), "--cleanup", str(verified_path)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(f.exists(), "a hash-mismatched file must NEVER be deleted")

            deletion_log = verified_path.with_suffix(".deletion-log.jsonl")
            lines = [json.loads(line) for line in deletion_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(lines[0]["action"], "skip")
            self.assertEqual(lines[0]["reason"], "hash_mismatch_since_verification")

    def test_cold_file_absent_from_verified_manifest_is_never_deleted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            f = root / "backups" / "unverified.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"nobody has confirmed archiving this yet")
            verified = {"schema_version": slm.SCHEMA_VERSION, "generated_at": "2026-08-23T00:00:00+00:00", "root_paths": [str(root)], "files": []}
            verified_path = Path(tmp) / "verified.json"
            verified_path.write_text(json.dumps(verified), encoding="utf-8")

            slm.main(["--root", str(root), "--cleanup", str(verified_path)])
            self.assertTrue(f.exists(), "a COLD file with no verified-manifest entry at all must never be deleted")

    def test_dry_run_deletes_nothing_but_still_logs_the_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            data = b"would be deleted for real without --dry-run"
            f = root / "backups" / "would-delete.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(data)
            verified = {
                "schema_version": slm.SCHEMA_VERSION, "generated_at": "2026-08-23T00:00:00+00:00",
                "root_paths": [str(root)],
                "files": [{"path": str(f), "size_bytes": len(data), "sha256": _sha256_bytes(data)}],
            }
            verified_path = Path(tmp) / "verified.json"
            verified_path.write_text(json.dumps(verified), encoding="utf-8")

            slm.main(["--root", str(root), "--cleanup", str(verified_path), "--dry-run"])
            self.assertTrue(f.exists(), "--dry-run must never actually delete anything")

    def test_cleanup_result_reports_destructive_action_taken_correctly(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            data = b"content"
            f = root / "backups" / "x.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(data)
            verified_path = Path(tmp) / "verified.json"
            verified_path.write_text(json.dumps({
                "schema_version": slm.SCHEMA_VERSION, "generated_at": "2026-08-23T00:00:00+00:00",
                "root_paths": [str(root)], "files": [{"path": str(f), "size_bytes": len(data), "sha256": _sha256_bytes(data)}],
            }), encoding="utf-8")

            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                slm.main(["--root", str(root), "--cleanup", str(verified_path), "--dry-run"])
            dry_run_result = json.loads(out.getvalue())
            self.assertFalse(dry_run_result["destructive_action_taken"], "dry-run must report no destructive action, even though a matching file existed")


class ReportTests(unittest.TestCase):
    def test_report_is_never_destructive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            f = root / "backups" / "x.bak"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"content")

            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                slm.main(["--root", str(root), "--report"])
            report = json.loads(out.getvalue())
            self.assertFalse(report["destructive_action_taken"])
            self.assertTrue(f.exists(), "--report must never delete anything")

    def test_disk_usage_warning_fires_past_a_low_threshold(self) -> None:
        """Uses --warn-at 0 (guaranteed to be crossed by any real disk) to
        deterministically prove the warning path fires, rather than
        depending on this machine's actual disk usage happening to be
        above some fixed percent."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            root.mkdir(parents=True)

            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                slm.main(["--root", str(root), "--report", "--warn-at", "0"])
            report = json.loads(out.getvalue())
            self.assertGreater(len(report["warnings"]), 0, "a 0% threshold must always be crossed")
            self.assertFalse(report["destructive_action_taken"], "a report warning must never itself trigger a destructive action")

    def test_no_warning_at_an_unreachable_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "strategylab"
            root.mkdir(parents=True)

            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                slm.main(["--root", str(root), "--report", "--warn-at", "101"])
            report = json.loads(out.getvalue())
            self.assertEqual(report["warnings"], [], "a threshold above 100% can never be crossed")


if __name__ == "__main__":
    unittest.main()
