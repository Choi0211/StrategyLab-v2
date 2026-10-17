"""Bounded daily storage maintenance for regenerable StrategyLab artifacts.

Safety contract:
- never deletes or compacts the live SQLite runtime database;
- never touches research_evidence, research_inputs, gaon-data, or secrets;
- old runtime backups are only gzip-compressed after byte-for-byte hash
  verification through the compressed stream; they are never auto-deleted;
- deletion is restricted to explicitly-named smoke/dev artifacts and pip
  cache entries older than conservative retention windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.scheduled_automation import (
    ScheduleDefinition,
    ScheduledJob,
    ScheduledJobRepository,
    ScheduledRunStatus,
)

_JOB_PREFIX = "gaon-storage-maintenance"
_BACKUP_AGE_DAYS = 14
_SMOKE_AGE_DAYS = 7
_CACHE_AGE_DAYS = 30


@dataclass(frozen=True)
class StorageMaintenanceResult:
    compressed_backups: tuple[str, ...]
    removed_artifacts: tuple[str, ...]
    pruned_worktree_metadata: bool
    bytes_before: int
    bytes_after: int

    @property
    def reclaimed_bytes(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    def to_json(self) -> dict[str, object]:
        return {
            "compressed_backups": list(self.compressed_backups),
            "removed_artifacts": list(self.removed_artifacts),
            "pruned_worktree_metadata": self.pruned_worktree_metadata,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "reclaimed_bytes": self.reclaimed_bytes,
            "live_database_touched": False,
            "research_evidence_touched": False,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
        }


def _utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _older_than(path: Path, cutoff: datetime) -> bool:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) < cutoff
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_gzip_payload(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compress_verified_backup(path: Path) -> Path:
    target = Path(str(path) + ".gz")
    if target.exists():
        return target
    tmp = Path(str(target) + ".tmp")
    source_hash = _sha256_file(path)
    with path.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    if _sha256_gzip_payload(tmp) != source_hash:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("compressed backup verification failed")
    os.replace(tmp, target)
    path.unlink()
    return target


def perform_storage_maintenance(
    *,
    state_root: str | Path = "/var/lib/strategylab",
    repo_root: str | Path = "/opt/strategylab-v2",
    now: str,
) -> StorageMaintenanceResult:
    at = _utc(now)
    state = Path(state_root).resolve()
    repo = Path(repo_root).resolve()
    before = _tree_bytes(state) + _tree_bytes(repo / ".cache")
    compressed: list[str] = []
    removed: list[str] = []

    # Backup compression: fixed filename prefix, root-local regular files only.
    backup_cutoff = at - timedelta(days=_BACKUP_AGE_DAYS)
    if state.is_dir():
        for path in sorted(state.glob("gaon-runtime-pre-*.sqlite")):
            if not path.is_file() or path.is_symlink() or not _older_than(path, backup_cutoff):
                continue
            target = _compress_verified_backup(path)
            compressed.append(str(target))

    # Explicit smoke/dev artifacts only. No wildcard over research/evidence data.
    smoke_cutoff = at - timedelta(days=_SMOKE_AGE_DAYS)
    for pattern in ("dev_worktrees_smoke*", "dev_repo_smoke*.git"):
        for path in sorted(state.glob(pattern)):
            if path.is_symlink() or not _older_than(path, smoke_cutoff):
                continue
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))

    # Regenerable pip cache only, file-by-file; leave directory layout intact.
    cache_cutoff = at - timedelta(days=_CACHE_AGE_DAYS)
    pip_cache = repo / ".cache" / "pip"
    if pip_cache.is_dir():
        for path in tuple(pip_cache.rglob("*")):
            if path.is_file() and not path.is_symlink() and _older_than(path, cache_cutoff):
                path.unlink(missing_ok=True)
                removed.append(str(path))
        for path in sorted((p for p in pip_cache.rglob("*") if p.is_dir()), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass

    # Git's own fixed command safely drops metadata for already-missing worktrees.
    pruned = False
    if (repo / ".git").exists():
        completed = subprocess.run(
            ["git", "-C", str(repo), "worktree", "prune", "--expire=now"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        pruned = completed.returncode == 0

    after = _tree_bytes(state) + _tree_bytes(repo / ".cache")
    return StorageMaintenanceResult(tuple(compressed), tuple(removed), pruned, before, after)


def _job_id(now: str) -> str:
    return f"{_JOB_PREFIX}:{now[:10]}"


def ensure_storage_maintenance_job(repository: ScheduledJobRepository, *, now: str) -> bool:
    job_id = _job_id(now)
    try:
        repository.get(job_id)
        return False
    except KeyError:
        pass
    repository.create(
        ScheduledJob(
            job_id=job_id,
            name="Gaon Storage Maintenance",
            request_text="storage_maintenance:bounded_daily",
            schedule=ScheduleDefinition("UTC", now, "manual"),
            enabled=True,
            created_at=now,
            updated_at=now,
            metadata={"kind": "storage_maintenance"},
            max_attempts=1,
        )
    )
    return True


@dataclass(frozen=True)
class StorageMaintenanceRuntimeTickResult:
    jobs_registered: bool
    attempted: bool
    results: tuple[StorageMaintenanceResult, ...] = ()
    error_type: str | None = None


class StorageMaintenanceRuntimeService:
    def __init__(
        self,
        repository: ScheduledJobRepository,
        *,
        metrics: MetricsCollector | None = None,
        now_factory=None,
        state_root: str | Path = "/var/lib/strategylab",
        repo_root: str | Path = "/opt/strategylab-v2",
    ) -> None:
        self._repository = repository
        self._metrics = metrics or MetricsCollector()
        self._now_factory = now_factory or (lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._state_root = state_root
        self._repo_root = repo_root

    def tick(self) -> StorageMaintenanceRuntimeTickResult:
        now = self._now_factory()
        try:
            registered = ensure_storage_maintenance_job(self._repository, now=now)
            results: list[StorageMaintenanceResult] = []
            for job in self._repository.due(now):
                if not job.job_id.startswith(_JOB_PREFIX + ":"):
                    continue
                run = self._repository.claim_run(job, now=now)
                if run is None:
                    continue
                result = perform_storage_maintenance(
                    state_root=self._state_root, repo_root=self._repo_root, now=now
                )
                self._repository.complete_run(
                    run, ScheduledRunStatus.SUCCEEDED, completed_at=now,
                    result={
                        "reclaimed_bytes": str(result.reclaimed_bytes),
                        "compressed_backups": str(len(result.compressed_backups)),
                        "removed_artifacts": str(len(result.removed_artifacts)),
                    },
                )
                results.append(result)
            self._metrics.increment("storage_maintenance_runtime_ticks", status="ok")
            return StorageMaintenanceRuntimeTickResult(registered, True, tuple(results))
        except Exception as exc:  # noqa: BLE001 - maintenance must never terminate production runtime.
            self._metrics.increment("storage_maintenance_runtime_ticks", status="failed")
            return StorageMaintenanceRuntimeTickResult(False, True, (), exc.__class__.__name__)
