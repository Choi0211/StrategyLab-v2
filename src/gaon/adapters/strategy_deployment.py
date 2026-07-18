"""Approval-gated strategy deployment workflow.

This module defines a generic deployment workflow for approved handoff packages.
It does not import private projects, execute broker orders, or shell out to
unbounded commands.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Protocol

from gaon.adapters.champion_registry import DEFAULT_CHAMPION_SLOT, SQLiteChampionRegistryRepository
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffPackage, StrategyHandoffStatus


STRATEGY_DEPLOYMENT_POLICY_VERSION = "strategy_deployment_policy_v1"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")


class StrategyDeploymentStatus(str, Enum):
    CREATED = "created"
    PREFLIGHT_PASSED = "preflight_passed"
    DRY_RUN_PASSED = "dry_run_passed"
    APPLYING = "applying"
    APPLIED = "applied"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StrategyDeploymentPolicy:
    policy_version: str = STRATEGY_DEPLOYMENT_POLICY_VERSION
    target_id: str = "generic-runtime"
    require_backup: bool = True
    require_dry_run: bool = True


@dataclass(frozen=True)
class StrategyDeploymentRequest:
    request_id: str
    package_id: str
    target_id: str
    actor_ref: str
    requested_at: str

    def __post_init__(self) -> None:
        _validate_ref(self.request_id.replace(":", "-"), "request_id")
        _validate_ref(self.package_id, "package_id")
        _validate_ref(self.target_id, "target_id")
        _validate_utc(self.requested_at)

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class StrategyDeploymentPlan:
    plan_id: str
    request_id: str
    package_id: str
    target_id: str
    package_checksum: str
    status: StrategyDeploymentStatus
    reason: str
    policy_version: str
    created_at: str

    def to_json(self) -> str:
        return _dumps(self.__dict__ | {"status": self.status.value})


@dataclass(frozen=True)
class StrategyDeploymentBackup:
    backup_id: str
    package_id: str
    previous_strategy_ref: str
    previous_strategy_version: str
    restore_ref: str
    created_at: str

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class StrategyDeploymentRun:
    run_id: str
    plan_id: str
    package_id: str
    target_id: str
    status: StrategyDeploymentStatus
    backup_id: str | None
    message: str
    started_at: str
    completed_at: str | None

    def to_json(self) -> str:
        return _dumps(self.__dict__ | {"status": self.status.value})


@dataclass(frozen=True)
class StrategyDeploymentResult:
    status: StrategyDeploymentStatus
    message: str
    modified_target: bool = False


class StrategyDeploymentAdapter(Protocol):
    def health_check(self) -> tuple[bool, str]: ...
    def get_active_strategy(self) -> dict[str, str]: ...
    def validate_package(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]: ...
    def create_backup(self, package: StrategyHandoffPackage, *, backup_id: str, created_at: str) -> StrategyDeploymentBackup: ...
    def dry_run_apply(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]: ...
    def apply_package(self, package: StrategyHandoffPackage) -> tuple[bool, str]: ...
    def restart_or_reload(self) -> tuple[bool, str]: ...
    def verify_active_strategy(self, package: StrategyHandoffPackage) -> tuple[bool, str]: ...
    def rollback(self, backup: StrategyDeploymentBackup) -> tuple[bool, str]: ...
    def get_deployment_status(self) -> dict[str, str]: ...


class FakeStrategyDeploymentAdapter:
    def __init__(self, *, fail_health: bool = False, fail_validate: bool = False, fail_backup: bool = False, fail_dry_run: bool = False, fail_apply: bool = False, fail_restart: bool = False, fail_verify: bool = False, fail_rollback: bool = False) -> None:
        self.fail_health = fail_health
        self.fail_validate = fail_validate
        self.fail_backup = fail_backup
        self.fail_dry_run = fail_dry_run
        self.fail_apply = fail_apply
        self.fail_restart = fail_restart
        self.fail_verify = fail_verify
        self.fail_rollback = fail_rollback
        self.active: dict[str, str] = {"strategy_ref": "previous", "strategy_version": "v0", "checksum": ""}
        self.backups: list[StrategyDeploymentBackup] = []
        self.applied = False
        self.dry_run_called = False

    def health_check(self) -> tuple[bool, str]:
        return (False, "fake target unhealthy") if self.fail_health else (True, "fake target healthy")

    def get_active_strategy(self) -> dict[str, str]:
        return dict(self.active)

    def validate_package(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]:
        if self.fail_validate:
            return False, ("target compatibility rejected",)
        if package.compatibility.supported_package_schema_version != package.manifest.schema_version:
            return False, ("schema version mismatch",)
        missing = [key for key in package.compatibility.required_parameter_keys if key not in package.parameters.parameters]
        return (not missing, tuple(f"missing parameter {key}" for key in missing))

    def create_backup(self, package: StrategyHandoffPackage, *, backup_id: str, created_at: str) -> StrategyDeploymentBackup:
        if self.fail_backup:
            raise RuntimeError("fake backup failure")
        backup = StrategyDeploymentBackup(backup_id, package.package_id, self.active.get("strategy_ref", "none"), self.active.get("strategy_version", "none"), f"fake-backup:{backup_id}", created_at)
        self.backups.append(backup)
        return backup

    def dry_run_apply(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]:
        self.dry_run_called = True
        return (False, ("fake dry-run failure",)) if self.fail_dry_run else (True, ())

    def apply_package(self, package: StrategyHandoffPackage) -> tuple[bool, str]:
        if self.fail_apply:
            return False, "fake apply failure"
        self.applied = True
        self.active = {"strategy_ref": package.manifest.strategy_ref, "strategy_version": package.manifest.strategy_version, "checksum": package.checksum}
        return True, "fake apply ok"

    def restart_or_reload(self) -> tuple[bool, str]:
        return (False, "fake restart failure") if self.fail_restart else (True, "fake restart ok")

    def verify_active_strategy(self, package: StrategyHandoffPackage) -> tuple[bool, str]:
        if self.fail_verify:
            return False, "fake verify failure"
        return (self.active.get("checksum") == package.checksum, "fake verify ok" if self.active.get("checksum") == package.checksum else "checksum mismatch")

    def rollback(self, backup: StrategyDeploymentBackup) -> tuple[bool, str]:
        if self.fail_rollback:
            return False, "fake rollback failure"
        self.applied = False
        self.active = {"strategy_ref": backup.previous_strategy_ref, "strategy_version": backup.previous_strategy_version, "checksum": ""}
        return True, "fake rollback ok"

    def get_deployment_status(self) -> dict[str, str]:
        return dict(self.active) | {"adapter": "fake"}


class LocalSafeStrategyDeploymentAdapter:
    def __init__(self, target_dir: str) -> None:
        self._target_dir = Path(target_dir).resolve()
        self._target_dir.mkdir(parents=True, exist_ok=True)
        self._active_file = self._target_dir / "active-strategy-package.json"

    def health_check(self) -> tuple[bool, str]:
        return (self._target_dir.exists() and self._target_dir.is_dir(), "local safe target directory ready")

    def get_active_strategy(self) -> dict[str, str]:
        if not self._active_file.exists():
            return {"strategy_ref": "none", "strategy_version": "none", "checksum": ""}
        payload = json.loads(self._active_file.read_text(encoding="utf-8"))
        manifest = payload.get("manifest", {})
        return {"strategy_ref": str(manifest.get("strategy_ref", "unknown")), "strategy_version": str(manifest.get("strategy_version", "unknown")), "checksum": str(manifest.get("checksum", ""))}

    def validate_package(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]:
        return (package.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT, () if package.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT else ("package not approved",))

    def create_backup(self, package: StrategyHandoffPackage, *, backup_id: str, created_at: str) -> StrategyDeploymentBackup:
        backup_file = self._target_dir / f"{backup_id}.json"
        if self._active_file.exists():
            shutil.copyfile(self._active_file, backup_file)
        else:
            backup_file.write_text("{}", encoding="utf-8")
        active = self.get_active_strategy()
        return StrategyDeploymentBackup(backup_id, package.package_id, active["strategy_ref"], active["strategy_version"], str(backup_file), created_at)

    def dry_run_apply(self, package: StrategyHandoffPackage) -> tuple[bool, tuple[str, ...]]:
        return True, ()

    def apply_package(self, package: StrategyHandoffPackage) -> tuple[bool, str]:
        self._active_file.write_text(package.to_json(), encoding="utf-8")
        return True, "local safe package applied"

    def restart_or_reload(self) -> tuple[bool, str]:
        return True, "local safe runtime has no restart command"

    def verify_active_strategy(self, package: StrategyHandoffPackage) -> tuple[bool, str]:
        return (self.get_active_strategy().get("checksum") == package.checksum, "local safe active checksum verified")

    def rollback(self, backup: StrategyDeploymentBackup) -> tuple[bool, str]:
        restore = Path(backup.restore_ref)
        if restore.exists():
            shutil.copyfile(restore, self._active_file)
            return True, "local safe rollback restored backup"
        return False, "backup file missing"

    def get_deployment_status(self) -> dict[str, str]:
        return self.get_active_strategy() | {"adapter": "local_safe"}


class SQLiteStrategyDeploymentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: StrategyDeploymentRequest) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_deployment_requests(request_id, package_id, target_id, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (request.request_id, request.package_id, request.target_id, StrategyDeploymentStatus.CREATED.value, request.to_json(), request.requested_at),
            )

    def add_plan(self, plan: StrategyDeploymentPlan) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_deployment_requests(request_id, package_id, target_id, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (plan.plan_id, plan.package_id, plan.target_id, plan.status.value, plan.to_json(), plan.created_at),
            )

    def get_plan(self, plan_id: str) -> StrategyDeploymentPlan:
        row = self._connection.execute("SELECT payload_json FROM strategy_deployment_requests WHERE request_id = ?", (plan_id,)).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return plan_from_json(str(row[0]))

    def list_plans(self) -> tuple[StrategyDeploymentPlan, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_deployment_requests ORDER BY created_at, request_id").fetchall()
        return tuple(plan_from_json(str(row[0])) for row in rows if str(row[0]).startswith("{\"created_at\""))

    def add_backup(self, backup: StrategyDeploymentBackup) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_deployment_backups(backup_id, package_id, restore_ref, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (backup.backup_id, backup.package_id, backup.restore_ref, backup.to_json(), backup.created_at),
            )

    def list_backups(self) -> tuple[StrategyDeploymentBackup, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_deployment_backups ORDER BY created_at, backup_id").fetchall()
        return tuple(backup_from_json(str(row[0])) for row in rows)

    def add_run(self, run: StrategyDeploymentRun) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_deployment_runs(run_id, plan_id, package_id, target_id, status, backup_id, payload_json, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.run_id, run.plan_id, run.package_id, run.target_id, run.status.value, run.backup_id, run.to_json(), run.started_at, run.completed_at),
            )

    def get_run(self, run_id: str) -> StrategyDeploymentRun:
        row = self._connection.execute("SELECT payload_json FROM strategy_deployment_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return run_from_json(str(row[0]))

    def list_runs(self) -> tuple[StrategyDeploymentRun, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_deployment_runs ORDER BY started_at, run_id").fetchall()
        return tuple(run_from_json(str(row[0])) for row in rows)

    def has_successful_deployment(self, package_id: str, target_id: str) -> bool:
        row = self._connection.execute("SELECT 1 FROM strategy_deployment_runs WHERE package_id = ? AND target_id = ? AND status = ? LIMIT 1", (package_id, target_id, StrategyDeploymentStatus.SUCCEEDED.value)).fetchone()
        return row is not None


class StrategyDeploymentService:
    def __init__(self, repository: SQLiteStrategyDeploymentRepository, handoffs: SQLiteStrategyHandoffRepository, registry: SQLiteChampionRegistryRepository, adapter: StrategyDeploymentAdapter, *, event_store: Any | None = None, metrics: Any | None = None, policy: StrategyDeploymentPolicy | None = None) -> None:
        self._repository = repository
        self._handoffs = handoffs
        self._registry = registry
        self._adapter = adapter
        self._event_store = event_store
        self._metrics = metrics
        self._policy = policy or StrategyDeploymentPolicy()

    def plan(self, request: StrategyDeploymentRequest) -> StrategyDeploymentPlan:
        self._repository.add_request(request)
        _increment(self._metrics, "gaon_strategy_deployments_total")
        package = self._handoffs.get_package(request.package_id)
        status, reason = self._preflight(package, request.target_id)
        plan = StrategyDeploymentPlan(f"deployment-plan:{request.request_id}", request.request_id, package.package_id, request.target_id, package.checksum, status, reason, self._policy.policy_version, request.requested_at)
        self._repository.add_plan(plan)
        self._record("StrategyDeploymentRequested", plan, request.actor_ref, request.requested_at, {"package_id": request.package_id})
        self._record("StrategyDeploymentPreflightPassed" if status == StrategyDeploymentStatus.PREFLIGHT_PASSED else "StrategyDeploymentBlocked", plan, request.actor_ref, request.requested_at, {"reason": reason})
        return plan

    def run(self, plan_id: str, *, actor_ref: str, at: str) -> StrategyDeploymentRun:
        plan = self._repository.get_plan(plan_id)
        package = self._handoffs.get_package(plan.package_id)
        if plan.status == StrategyDeploymentStatus.BLOCKED:
            run = self._run(plan, StrategyDeploymentStatus.BLOCKED, None, plan.reason, at)
            return run
        if self._repository.has_successful_deployment(plan.package_id, plan.target_id):
            run = self._run(plan, StrategyDeploymentStatus.BLOCKED, None, "duplicate deployment prevented", at)
            self._record("StrategyDeploymentBlocked", plan, actor_ref, at, {"reason": run.message})
            return run
        backup: StrategyDeploymentBackup | None = None
        modified = False
        try:
            backup = self._adapter.create_backup(package, backup_id=f"deployment-backup:{plan.plan_id}", created_at=at)
            self._repository.add_backup(backup)
            self._record("StrategyDeploymentBackupCreated", plan, actor_ref, at, {"backup_id": backup.backup_id})
            ok, reasons = self._adapter.dry_run_apply(package)
            if not ok:
                return self._fail(plan, backup, "dry-run failed: " + "; ".join(reasons), actor_ref, at, modified=False)
            self._record("StrategyDeploymentDryRunPassed", plan, actor_ref, at, {})
            ok, message = self._adapter.apply_package(package)
            modified = ok
            if not ok:
                return self._fail(plan, backup, message, actor_ref, at, modified=False)
            self._record("StrategyDeploymentApplied", plan, actor_ref, at, {"message": message})
            ok, message = self._adapter.restart_or_reload()
            if not ok:
                return self._fail(plan, backup, message, actor_ref, at, modified=True)
            ok, message = self._adapter.health_check()
            if not ok:
                return self._fail(plan, backup, message, actor_ref, at, modified=True)
            self._record("StrategyDeploymentVerified", plan, actor_ref, at, {})
            ok, message = self._adapter.verify_active_strategy(package)
            if not ok:
                return self._fail(plan, backup, message, actor_ref, at, modified=True)
            run = self._run(plan, StrategyDeploymentStatus.SUCCEEDED, backup.backup_id, "deployment succeeded", at)
            self._record("StrategyDeploymentSucceeded", plan, actor_ref, at, {"run_id": run.run_id})
            _increment(self._metrics, "gaon_strategy_deployments_succeeded_total")
            return run
        except Exception as exc:  # noqa: BLE001 - deployment failures must be surfaced and persisted.
            return self._fail(plan, backup, exc.__class__.__name__, actor_ref, at, modified=modified)

    def _preflight(self, package: StrategyHandoffPackage, target_id: str) -> tuple[StrategyDeploymentStatus, str]:
        if package.status != StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT:
            return StrategyDeploymentStatus.BLOCKED, "handoff package is not approved for deployment"
        approval = self._handoffs.latest_approval(package.package_id)
        if approval is None or not approval.approved or approval.package_checksum != package.checksum:
            return StrategyDeploymentStatus.BLOCKED, "package-specific approval checksum is missing or stale"
        active = self._registry.get_active(DEFAULT_CHAMPION_SLOT)
        if active is None or active.active_version_id != package.manifest.champion_registry_version or active.fingerprint != package.manifest.champion_fingerprint:
            return StrategyDeploymentStatus.BLOCKED, "Champion version no longer matches package"
        ok, message = self._adapter.health_check()
        if not ok:
            return StrategyDeploymentStatus.BLOCKED, message
        ok, reasons = self._adapter.validate_package(package)
        if not ok:
            return StrategyDeploymentStatus.BLOCKED, "; ".join(reasons)
        if target_id != self._policy.target_id:
            return StrategyDeploymentStatus.BLOCKED, "target policy mismatch"
        return StrategyDeploymentStatus.PREFLIGHT_PASSED, "preflight passed"

    def _fail(self, plan: StrategyDeploymentPlan, backup: StrategyDeploymentBackup | None, message: str, actor_ref: str, at: str, *, modified: bool) -> StrategyDeploymentRun:
        self._record("StrategyDeploymentFailed", plan, actor_ref, at, {"message": message})
        _increment(self._metrics, "gaon_strategy_deployments_failed_total")
        if modified and backup is not None:
            self._record("StrategyDeploymentRollbackStarted", plan, actor_ref, at, {"backup_id": backup.backup_id})
            _increment(self._metrics, "gaon_strategy_deployment_rollbacks_total")
            ok, rollback_message = self._adapter.rollback(backup)
            if ok:
                run = self._run(plan, StrategyDeploymentStatus.ROLLED_BACK, backup.backup_id, rollback_message, at)
                self._record("StrategyDeploymentRolledBack", plan, actor_ref, at, {"run_id": run.run_id})
                return run
            run = self._run(plan, StrategyDeploymentStatus.ROLLBACK_FAILED, backup.backup_id, rollback_message, at)
            self._record("StrategyDeploymentRollbackFailed", plan, actor_ref, at, {"run_id": run.run_id})
            _increment(self._metrics, "gaon_strategy_deployment_rollback_failures_total")
            return run
        return self._run(plan, StrategyDeploymentStatus.FAILED, backup.backup_id if backup else None, message, at)

    def _run(self, plan: StrategyDeploymentPlan, status: StrategyDeploymentStatus, backup_id: str | None, message: str, at: str) -> StrategyDeploymentRun:
        run = StrategyDeploymentRun(f"deployment-run:{plan.plan_id}", plan.plan_id, plan.package_id, plan.target_id, status, backup_id, message, at, at)
        self._repository.add_run(run)
        return run

    def _record(self, event_type: str, plan: StrategyDeploymentPlan, actor_ref: str, at: str, payload: dict[str, object]) -> None:
        if self._event_store is None:
            return
        from gaon.runtime.event_store import DurableEvent

        try:
            self._event_store.append(
                DurableEvent(
                    f"event:strategy-deployment:{event_type}:{plan.plan_id}",
                    event_type,
                    at,
                    actor_ref,
                    plan.plan_id,
                    plan.package_id,
                    "strategy_deployment",
                    "StrategyLab",
                    "N/A",
                    "N/A",
                    payload | {"plan_id": plan.plan_id, "package_id": plan.package_id, "status": plan.status.value},
                    (plan.package_id,),
                    (),
                    at,
                )
            )
        except sqlite3.IntegrityError:
            return


def build_strategy_deployment_request(request_id: str, *, package_id: str, actor_ref: str, requested_at: str, target_id: str = "generic-runtime") -> StrategyDeploymentRequest:
    return StrategyDeploymentRequest(request_id, package_id, target_id, actor_ref, requested_at)


def plan_from_json(value: str) -> StrategyDeploymentPlan:
    payload = json.loads(value)
    if "plan_id" not in payload:
        raise ValueError("payload is not a deployment plan")
    return StrategyDeploymentPlan(str(payload["plan_id"]), str(payload["request_id"]), str(payload["package_id"]), str(payload["target_id"]), str(payload["package_checksum"]), StrategyDeploymentStatus(str(payload["status"])), str(payload["reason"]), str(payload["policy_version"]), str(payload["created_at"]))


def backup_from_json(value: str) -> StrategyDeploymentBackup:
    payload = json.loads(value)
    return StrategyDeploymentBackup(str(payload["backup_id"]), str(payload["package_id"]), str(payload["previous_strategy_ref"]), str(payload["previous_strategy_version"]), str(payload["restore_ref"]), str(payload["created_at"]))


def run_from_json(value: str) -> StrategyDeploymentRun:
    payload = json.loads(value)
    return StrategyDeploymentRun(str(payload["run_id"]), str(payload["plan_id"]), str(payload["package_id"]), str(payload["target_id"]), StrategyDeploymentStatus(str(payload["status"])), payload.get("backup_id"), str(payload["message"]), str(payload["started_at"]), payload.get("completed_at"))


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_ref(value: str, label: str) -> None:
    if SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe reference")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name)
