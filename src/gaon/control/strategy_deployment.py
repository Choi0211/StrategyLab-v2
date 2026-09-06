"""Priority 2 / D2 + D3 - the one-click safe apply / rollback lifecycle.

The Web [apply this version] / [rollback to this] button does NOT touch
systemctl or a config file. It calls ``StrategyDeploymentController``,
which runs ONE bounded lifecycle:

  REQUESTED -> VALIDATED -> ENTRY_BLOCKED -> RUNTIME_PRECONDITIONS_OK
  -> VERSION_APPLIED -> EFFECTIVE_VERSION_VERIFIED -> ACTIVE

and drops to FAILED_CLOSED on ANY step failure.

Core invariant: a mid-lifecycle failure NEVER loses the strategy that
was ACTIVE. The registry's ACTIVE pointer is moved only at the very last
step; on failure the runtime is best-effort restored to the previous
version and entries stay blocked.

Rollback is the SAME lifecycle with a PREVIOUS version as the target.

Isolated - ``FakeStrategyRuntime`` only; the real runtime adapter is an
unimplemented ``StrategyRuntime`` Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Protocol

from gaon.control.strategy_version import (
    StrategyVersionRegistry,
    StrategyVersionStatus,
)


class DeployStep(str, Enum):
    REQUESTED = "requested"
    VALIDATED = "validated"
    ENTRY_BLOCKED = "entry_blocked"
    RUNTIME_PRECONDITIONS_OK = "runtime_preconditions_ok"
    VERSION_APPLIED = "version_applied"
    EFFECTIVE_VERSION_VERIFIED = "effective_version_verified"
    ACTIVE = "active"
    FAILED_CLOSED = "failed_closed"


class DeployOutcome(str, Enum):
    ACTIVE = "active"
    FAILED_CLOSED = "failed_closed"


class StrategyRuntime(Protocol):
    def effective_fingerprint(self) -> str: ...
    def apply_version(self, spec_rules: Mapping[str, object], spec_fingerprint: str) -> None: ...
    def block_entries(self) -> None: ...
    def unblock_entries(self) -> None: ...


class FakeStrategyRuntime:
    """In-memory runtime for tests. ``fail_on`` in {"apply", "verify"}
    exercises the FAILED_CLOSED paths ("verify" makes the NEXT
    ``effective_fingerprint`` read after an apply report drift, once)."""

    def __init__(self, *, effective: str = "fp-none") -> None:
        self._effective = effective
        self.entries_blocked = False
        self.fail_on: str | None = None
        self.applied_history: list[str] = []
        self._pending_verify_fail = False

    def effective_fingerprint(self) -> str:
        if self._pending_verify_fail:
            self._pending_verify_fail = False
            return f"{self._effective}::drift"
        return self._effective

    def apply_version(self, spec_rules: Mapping[str, object], spec_fingerprint: str) -> None:
        self.applied_history.append(spec_fingerprint)
        if self.fail_on == "apply":
            raise RuntimeError("fake runtime: apply failed")
        self._effective = spec_fingerprint
        self._pending_verify_fail = self.fail_on == "verify"

    def block_entries(self) -> None:
        self.entries_blocked = True

    def unblock_entries(self) -> None:
        self.entries_blocked = False


@dataclass
class DeploymentResult:
    result: DeployOutcome
    active_version_id: str | None
    steps: list[DeployStep] = field(default_factory=list)
    last_error: str | None = None


class _DeployFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StrategyDeploymentController:
    def __init__(self, registry: StrategyVersionRegistry, runtime: StrategyRuntime) -> None:
        self._registry = registry
        self._runtime = runtime

    def request_apply(
        self,
        strategy_version_id: str,
        *,
        at: str,
        validate: Callable[[object], bool] | None = None,
        precheck: Callable[[], bool] | None = None,
    ) -> DeploymentResult:
        return self._deploy(strategy_version_id, at=at, validate=validate, precheck=precheck)

    # rollback IS an apply, targeting a PREVIOUS version - same lifecycle,
    # same safety, kept as a distinct method for call-site clarity.
    def request_rollback(
        self,
        strategy_version_id: str,
        *,
        at: str,
        validate: Callable[[object], bool] | None = None,
        precheck: Callable[[], bool] | None = None,
    ) -> DeploymentResult:
        return self._deploy(strategy_version_id, at=at, validate=validate, precheck=precheck)

    def _deploy(
        self,
        strategy_version_id: str,
        *,
        at: str,
        validate: Callable[[object], bool] | None,
        precheck: Callable[[], bool] | None,
    ) -> DeploymentResult:
        validate = validate or (lambda _v: True)
        precheck = precheck or (lambda: True)
        steps: list[DeployStep] = []

        target = self._registry.get(strategy_version_id)  # KeyError propagates - unknown id is a caller bug
        previous_active = self._registry.active()
        applied_to_runtime = False

        try:
            steps.append(DeployStep.REQUESTED)
            if target.status is StrategyVersionStatus.RETIRED:
                raise _DeployFailure("target strategy version is RETIRED")

            steps.append(DeployStep.VALIDATED)
            if not validate(target):
                raise _DeployFailure("strategy validation did not pass")

            steps.append(DeployStep.ENTRY_BLOCKED)
            self._runtime.block_entries()

            steps.append(DeployStep.RUNTIME_PRECONDITIONS_OK)
            if not precheck():
                raise _DeployFailure("runtime preconditions not met")

            steps.append(DeployStep.VERSION_APPLIED)
            applied_to_runtime = True
            self._runtime.apply_version(target.spec_rules, target.spec_fingerprint)

            steps.append(DeployStep.EFFECTIVE_VERSION_VERIFIED)
            if self._runtime.effective_fingerprint() != target.spec_fingerprint:
                raise _DeployFailure("effective runtime fingerprint does not match the target version")

            # commit LAST - the registry ACTIVE pointer moves only here.
            self._registry.mark_active(strategy_version_id, at=at)
            self._runtime.unblock_entries()
            steps.append(DeployStep.ACTIVE)
            return DeploymentResult(DeployOutcome.ACTIVE, strategy_version_id, steps, None)
        except Exception as exc:  # noqa: BLE001 - any failure is FAILED_CLOSED
            reason = getattr(exc, "reason", type(exc).__name__)
            if applied_to_runtime and previous_active is not None:
                try:
                    self._runtime.apply_version(previous_active.spec_rules, previous_active.spec_fingerprint)
                except Exception:  # noqa: BLE001 - best effort; ACTIVE pointer already unchanged
                    pass
            steps.append(DeployStep.FAILED_CLOSED)
            return DeploymentResult(
                DeployOutcome.FAILED_CLOSED,
                previous_active.strategy_version_id if previous_active else None,
                steps,
                reason,
            )
