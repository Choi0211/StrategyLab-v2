"""Approved Champion strategy handoff packages.

The handoff package is a portable, deterministic description of an approved
Champion. It contains no executable code, broker credentials, account IDs, or
private repository assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from gaon.adapters.backtest import BacktestResult, SQLiteBacktestRepository
from gaon.adapters.champion_registry import DEFAULT_CHAMPION_SLOT, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationStatus, SQLitePaperRevalidationRepository


STRATEGY_HANDOFF_SCHEMA_VERSION = 1
STRATEGY_HANDOFF_POLICY_VERSION = "strategy_handoff_policy_v1"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
PRIMITIVE = str | int | float | bool


class StrategyHandoffStatus(str, Enum):
    CREATED = "created"
    PENDING_APPROVAL = "pending_approval"
    APPROVED_FOR_DEPLOYMENT = "approved_for_deployment"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class StrategyParameterSet:
    parameters: dict[str, PRIMITIVE]

    def __post_init__(self) -> None:
        for key, value in self.parameters.items():
            _validate_key(key)
            if type(value) not in {str, int, float, bool}:  # noqa: E721 - bool is an int subclass.
                raise ValueError("strategy parameters must be primitive JSON values")

    def as_dict(self) -> dict[str, PRIMITIVE]:
        return dict(sorted(self.parameters.items()))


@dataclass(frozen=True)
class StrategyCompatibilityContract:
    required_strategy_id: str
    required_parameter_keys: tuple[str, ...]
    parameter_types: dict[str, str]
    supported_package_schema_version: int = STRATEGY_HANDOFF_SCHEMA_VERSION
    target_runtime_compatibility_version: str = "generic-strategy-runtime-v1"

    def __post_init__(self) -> None:
        _validate_ref(self.required_strategy_id, "required_strategy_id")
        for key in self.required_parameter_keys:
            _validate_key(key)
        if tuple(sorted(self.required_parameter_keys)) != self.required_parameter_keys:
            raise ValueError("required parameter keys must be sorted")
        if set(self.required_parameter_keys) != set(self.parameter_types):
            raise ValueError("parameter type map must match required keys")

    def as_dict(self) -> dict[str, object]:
        return {
            "required_strategy_id": self.required_strategy_id,
            "required_parameter_keys": list(self.required_parameter_keys),
            "parameter_types": dict(sorted(self.parameter_types.items())),
            "supported_package_schema_version": self.supported_package_schema_version,
            "target_runtime_compatibility_version": self.target_runtime_compatibility_version,
        }


@dataclass(frozen=True)
class StrategyHandoffManifest:
    package_id: str
    schema_version: int
    strategy_ref: str
    strategy_version: str
    champion_registry_version: str
    champion_fingerprint: str
    source_backtest_id: str
    source_backtest_fingerprint: str
    validation_id: str
    champion_evaluation_id: str
    paper_session_id: str
    paper_revalidation_id: str
    policy_versions: tuple[str, ...]
    generated_at: str
    checksum: str

    def __post_init__(self) -> None:
        _validate_ref(self.package_id, "package_id")
        _validate_ref(self.strategy_ref, "strategy_ref")
        _validate_ref(self.champion_fingerprint, "champion_fingerprint")
        _validate_utc(self.generated_at)
        if self.schema_version != STRATEGY_HANDOFF_SCHEMA_VERSION:
            raise ValueError("unsupported handoff package schema version")

    def as_dict(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "schema_version": self.schema_version,
            "strategy_ref": self.strategy_ref,
            "strategy_version": self.strategy_version,
            "champion_registry_version": self.champion_registry_version,
            "champion_fingerprint": self.champion_fingerprint,
            "source_backtest_id": self.source_backtest_id,
            "source_backtest_fingerprint": self.source_backtest_fingerprint,
            "validation_id": self.validation_id,
            "champion_evaluation_id": self.champion_evaluation_id,
            "paper_session_id": self.paper_session_id,
            "paper_revalidation_id": self.paper_revalidation_id,
            "policy_versions": list(self.policy_versions),
            "generated_at": self.generated_at,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class StrategyHandoffRequest:
    request_id: str
    champion_slot: str
    revalidation_id: str
    actor_ref: str
    requested_at: str

    def __post_init__(self) -> None:
        _validate_ref(self.request_id.replace(":", "-"), "request_id")
        _validate_ref(self.champion_slot, "champion_slot")
        _validate_utc(self.requested_at)


@dataclass(frozen=True)
class StrategyDeploymentApproval:
    approval_id: str
    package_id: str
    package_checksum: str
    approver_ref: str
    approved: bool
    decided_at: str
    reason: str

    def __post_init__(self) -> None:
        _validate_ref(self.approval_id.replace(":", "-"), "approval_id")
        _validate_ref(self.package_id, "package_id")
        _validate_utc(self.decided_at)
        if not self.approver_ref:
            raise ValueError("approval requires approver_ref")

    def to_json(self) -> str:
        return _dumps(self.__dict__)


@dataclass(frozen=True)
class StrategyHandoffPackage:
    package_id: str
    status: StrategyHandoffStatus
    manifest: StrategyHandoffManifest
    parameters: StrategyParameterSet
    compatibility: StrategyCompatibilityContract
    created_by: str
    approval_required: bool = True
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None

    def __post_init__(self) -> None:
        if self.package_id != self.manifest.package_id:
            raise ValueError("package id must match manifest")
        if self.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT and (not self.approved_by or not self.approved_at):
            raise ValueError("approved handoff package requires approval metadata")
        if self.approved_at is not None:
            _validate_utc(self.approved_at)
        if self.rejected_at is not None:
            _validate_utc(self.rejected_at)

    @property
    def checksum(self) -> str:
        return self.manifest.checksum

    def payload_without_checksum(self) -> dict[str, object]:
        manifest = self.manifest.as_dict() | {"checksum": ""}
        return {
            "kind": "strategy_handoff_package",
            "schema_version": STRATEGY_HANDOFF_SCHEMA_VERSION,
            "package_id": self.package_id,
            "manifest": manifest,
            "parameters": self.parameters.as_dict(),
            "compatibility": self.compatibility.as_dict(),
            "created_by": self.created_by,
            "approval_required": self.approval_required,
        }

    def payload(self) -> dict[str, object]:
        return self.payload_without_checksum() | {
            "status": self.status.value,
            "manifest": self.manifest.as_dict(),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at,
        }

    def to_json(self) -> str:
        return _dumps(self.payload())

    def with_status(self, status: StrategyHandoffStatus, *, actor_ref: str, at: str) -> "StrategyHandoffPackage":
        if self.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT and status != self.status:
            raise ValueError("approved handoff packages are immutable")
        if status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT:
            return replace(self, status=status, approved_by=actor_ref, approved_at=at)
        if status == StrategyHandoffStatus.REJECTED:
            return replace(self, status=status, rejected_by=actor_ref, rejected_at=at)
        return replace(self, status=status)


class SQLiteStrategyHandoffRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_package(self, package: StrategyHandoffPackage) -> None:
        existing = self.get_package_or_none(package.package_id)
        if existing is not None:
            if existing.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT and existing.to_json() != package.to_json():
                raise ValueError("approved handoff package is immutable")
            raise sqlite3.IntegrityError(f"handoff package already exists: {package.package_id}")
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_handoff_packages(package_id, status, checksum, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (package.package_id, package.status.value, package.checksum, package.to_json(), package.manifest.generated_at),
            )

    def update_package(self, package: StrategyHandoffPackage) -> None:
        existing = self.get_package(package.package_id)
        if existing.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT and existing.to_json() != package.to_json():
            raise ValueError("approved handoff package is immutable")
        with self._connection:
            updated = self._connection.execute(
                "UPDATE strategy_handoff_packages SET status = ?, checksum = ?, payload_json = ? WHERE package_id = ?",
                (package.status.value, package.checksum, package.to_json(), package.package_id),
            ).rowcount
            if updated != 1:
                raise KeyError(package.package_id)

    def get_package_or_none(self, package_id: str) -> StrategyHandoffPackage | None:
        row = self._connection.execute("SELECT payload_json FROM strategy_handoff_packages WHERE package_id = ?", (package_id,)).fetchone()
        return package_from_json(str(row[0])) if row else None

    def get_package(self, package_id: str) -> StrategyHandoffPackage:
        package = self.get_package_or_none(package_id)
        if package is None:
            raise KeyError(package_id)
        return package

    def list_packages(self) -> tuple[StrategyHandoffPackage, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_handoff_packages ORDER BY created_at, package_id").fetchall()
        return tuple(package_from_json(str(row[0])) for row in rows)

    def add_approval(self, approval: StrategyDeploymentApproval) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_handoff_approvals(approval_id, package_id, approved, package_checksum, approver_ref, decided_at, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (approval.approval_id, approval.package_id, int(approval.approved), approval.package_checksum, approval.approver_ref, approval.decided_at, approval.to_json()),
            )

    def latest_approval(self, package_id: str) -> StrategyDeploymentApproval | None:
        row = self._connection.execute("SELECT package_checksum, payload_json FROM strategy_handoff_approvals WHERE package_id = ? ORDER BY decided_at DESC, approval_id DESC LIMIT 1", (package_id,)).fetchone()
        if row is None:
            return None
        approval = approval_from_json(str(row[1]))
        if approval.package_checksum != str(row[0]):
            return replace(approval, package_checksum=str(row[0]))
        return approval


class StrategyHandoffService:
    def __init__(
        self,
        repository: SQLiteStrategyHandoffRepository,
        registry: SQLiteChampionRegistryRepository,
        revalidations: SQLitePaperRevalidationRepository,
        backtests: SQLiteBacktestRepository,
        *,
        event_store: Any | None = None,
        metrics: Any | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._revalidations = revalidations
        self._backtests = backtests
        self._event_store = event_store
        self._metrics = metrics

    def create(self, request: StrategyHandoffRequest) -> StrategyHandoffPackage:
        active = self._registry.get_active(request.champion_slot)
        if active is None:
            raise ValueError("active Champion is required for handoff")
        report = self._revalidations.get_report(request.revalidation_id)
        if report.status != PaperRevalidationStatus.LIVE_ELIGIBLE:
            raise ValueError(f"{report.status.value} revalidation is not deployable by default")
        if report.champion_version_id != active.active_version_id or report.fingerprint != active.fingerprint:
            raise ValueError("paper revalidation does not match active Champion fingerprint")
        backtest = self._backtests.get_result(active.source_backtest_id)
        if backtest.fingerprint != active.fingerprint:
            raise ValueError("Champion fingerprint does not match source backtest")
        package = build_handoff_package(request, active, report, backtest)
        self._record("StrategyHandoffRequested", package, request.actor_ref, request.requested_at)
        self._repository.add_package(package)
        self._record("StrategyHandoffPackageCreated", package, request.actor_ref, request.requested_at)
        self._record("StrategyHandoffApprovalRequested", package, request.actor_ref, request.requested_at)
        _increment(self._metrics, "gaon_strategy_handoff_packages_total")
        return package

    def approve(self, package_id: str, *, approver_ref: str, decided_at: str, reason: str = "explicit human approval") -> StrategyHandoffPackage:
        package = self._repository.get_package(package_id)
        if package.status == StrategyHandoffStatus.REJECTED:
            raise ValueError("rejected handoff package cannot be approved")
        approval = StrategyDeploymentApproval(f"handoff-approval:{package_id}", package_id, package.checksum, approver_ref, True, decided_at, reason)
        self._repository.add_approval(approval)
        approved = package.with_status(StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT, actor_ref=approver_ref, at=decided_at)
        self._repository.update_package(approved)
        self._record("StrategyHandoffApproved", approved, approver_ref, decided_at)
        _increment(self._metrics, "gaon_strategy_handoff_approvals_total")
        return approved

    def reject(self, package_id: str, *, actor_ref: str, decided_at: str, reason: str) -> StrategyHandoffPackage:
        package = self._repository.get_package(package_id)
        if package.status == StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT:
            raise ValueError("approved handoff package is immutable")
        approval = StrategyDeploymentApproval(f"handoff-rejection:{package_id}", package_id, package.checksum, actor_ref, False, decided_at, reason)
        self._repository.add_approval(approval)
        rejected = package.with_status(StrategyHandoffStatus.REJECTED, actor_ref=actor_ref, at=decided_at)
        self._repository.update_package(rejected)
        self._record("StrategyHandoffRejected", rejected, actor_ref, decided_at)
        _increment(self._metrics, "gaon_strategy_handoff_rejections_total")
        return rejected

    def _record(self, event_type: str, package: StrategyHandoffPackage, actor_ref: str, at: str) -> None:
        if self._event_store is None:
            return
        from gaon.runtime.event_store import DurableEvent

        try:
            self._event_store.append(
                DurableEvent(
                    f"event:strategy-handoff:{event_type}:{package.package_id}",
                    event_type,
                    at,
                    actor_ref,
                    package.package_id,
                    package.manifest.paper_revalidation_id,
                    "strategy_handoff",
                    "StrategyLab",
                    package.manifest.strategy_ref,
                    "N/A",
                    {"package_id": package.package_id, "status": package.status.value, "checksum": package.checksum},
                    (package.manifest.source_backtest_id, package.manifest.paper_revalidation_id),
                    (),
                    at,
                )
            )
        except sqlite3.IntegrityError:
            return


def build_strategy_handoff_request(request_id: str, *, revalidation_id: str, actor_ref: str, requested_at: str, champion_slot: str = DEFAULT_CHAMPION_SLOT) -> StrategyHandoffRequest:
    return StrategyHandoffRequest(request_id, champion_slot, revalidation_id, actor_ref, requested_at)


def build_handoff_package(request: StrategyHandoffRequest, active: Any, report: Any, backtest: BacktestResult) -> StrategyHandoffPackage:
    parameters = StrategyParameterSet(dict(backtest.parameters))
    keys = tuple(sorted(parameters.parameters))
    contract = StrategyCompatibilityContract(
        required_strategy_id=backtest.strategy.strategy_id,
        required_parameter_keys=keys,
        parameter_types={key: type(parameters.parameters[key]).__name__ for key in keys},
    )
    package_id = f"handoff-{_short_hash(active.active_version_id + ':' + request.revalidation_id)}"
    manifest = StrategyHandoffManifest(
        package_id=package_id,
        schema_version=STRATEGY_HANDOFF_SCHEMA_VERSION,
        strategy_ref=active.strategy_ref,
        strategy_version=backtest.strategy.version,
        champion_registry_version=active.active_version_id,
        champion_fingerprint=active.fingerprint,
        source_backtest_id=active.source_backtest_id,
        source_backtest_fingerprint=backtest.fingerprint,
        validation_id=active.source_validation_id,
        champion_evaluation_id=active.source_evaluation_id,
        paper_session_id=report.session_id,
        paper_revalidation_id=report.revalidation_id,
        policy_versions=(STRATEGY_HANDOFF_POLICY_VERSION, report.policy_version),
        generated_at=request.requested_at,
        checksum="",
    )
    package = StrategyHandoffPackage(package_id, StrategyHandoffStatus.PENDING_APPROVAL, manifest, parameters, contract, request.actor_ref)
    checksum = _checksum(package.payload_without_checksum())
    return replace(package, manifest=replace(manifest, checksum=checksum))


def package_from_json(value: str) -> StrategyHandoffPackage:
    payload = json.loads(value)
    if payload.get("kind") != "strategy_handoff_package" or int(payload.get("schema_version", -1)) != STRATEGY_HANDOFF_SCHEMA_VERSION:
        raise ValueError("unsupported handoff package JSON")
    manifest_payload = payload["manifest"]
    manifest = StrategyHandoffManifest(
        package_id=str(manifest_payload["package_id"]),
        schema_version=int(manifest_payload["schema_version"]),
        strategy_ref=str(manifest_payload["strategy_ref"]),
        strategy_version=str(manifest_payload["strategy_version"]),
        champion_registry_version=str(manifest_payload["champion_registry_version"]),
        champion_fingerprint=str(manifest_payload["champion_fingerprint"]),
        source_backtest_id=str(manifest_payload["source_backtest_id"]),
        source_backtest_fingerprint=str(manifest_payload["source_backtest_fingerprint"]),
        validation_id=str(manifest_payload["validation_id"]),
        champion_evaluation_id=str(manifest_payload["champion_evaluation_id"]),
        paper_session_id=str(manifest_payload["paper_session_id"]),
        paper_revalidation_id=str(manifest_payload["paper_revalidation_id"]),
        policy_versions=tuple(str(item) for item in manifest_payload["policy_versions"]),
        generated_at=str(manifest_payload["generated_at"]),
        checksum=str(manifest_payload["checksum"]),
    )
    package = StrategyHandoffPackage(
        package_id=str(payload["package_id"]),
        status=StrategyHandoffStatus(str(payload["status"])),
        manifest=manifest,
        parameters=StrategyParameterSet(dict(payload["parameters"])),
        compatibility=StrategyCompatibilityContract(
            required_strategy_id=str(payload["compatibility"]["required_strategy_id"]),
            required_parameter_keys=tuple(str(item) for item in payload["compatibility"]["required_parameter_keys"]),
            parameter_types={str(key): str(value) for key, value in payload["compatibility"]["parameter_types"].items()},
            supported_package_schema_version=int(payload["compatibility"]["supported_package_schema_version"]),
            target_runtime_compatibility_version=str(payload["compatibility"]["target_runtime_compatibility_version"]),
        ),
        created_by=str(payload["created_by"]),
        approval_required=bool(payload["approval_required"]),
        approved_by=payload.get("approved_by"),
        approved_at=payload.get("approved_at"),
        rejected_by=payload.get("rejected_by"),
        rejected_at=payload.get("rejected_at"),
    )
    if _checksum(package.payload_without_checksum()) != package.checksum:
        raise ValueError("handoff package checksum mismatch")
    return package


def approval_from_json(value: str) -> StrategyDeploymentApproval:
    payload = json.loads(value)
    return StrategyDeploymentApproval(
        approval_id=str(payload["approval_id"]),
        package_id=str(payload["package_id"]),
        package_checksum=str(payload["package_checksum"]),
        approver_ref=str(payload["approver_ref"]),
        approved=bool(payload["approved"]),
        decided_at=str(payload["decided_at"]),
        reason=str(payload["reason"]),
    )


def safe_handoff_export_path(output: str) -> Path:
    target = Path(output).resolve()
    cwd = Path.cwd().resolve()
    if cwd != target and cwd not in target.parents:
        raise ValueError("handoff export path must stay within the current working directory")
    return target


def _checksum(payload: dict[str, object]) -> str:
    return hashlib.sha256(_dumps(payload).encode("utf-8")).hexdigest()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _validate_ref(value: str, label: str) -> None:
    if SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe reference")


def _validate_key(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
        raise ValueError("parameter keys must be safe identifiers")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name)
