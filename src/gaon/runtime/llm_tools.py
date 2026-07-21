"""Safe read-only tool calling framework for Gaon's LLM brain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import sqlite3
from typing import Callable
from uuid import uuid4

from gaon.runtime.assistant_provider import AssistantToolDefinition
from gaon.runtime.external_research import ExternalResearchTool, structured_data
from gaon.runtime.serialization import dumps_json, loads_json
from gaon.research.quant_research import KRXMarketDataTool


class ToolRiskLevel(str, Enum):
    READ_ONLY = "read_only"
    SAFE_WRITE = "safe_write"
    APPROVAL_REQUIRED = "approval_required"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: ToolRiskLevel
    required_args: tuple[str, ...] = ()
    allowed_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: dict[str, object]
    requested_by: str
    requested_at: str
    approval_ref: str | None = None


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: str
    output: dict[str, object]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolAuditRecord:
    audit_id: str
    tool_name: str
    status: str
    risk_level: str
    request: dict[str, object]
    result: dict[str, object]
    created_at: str


class ToolSecurityError(Exception):
    """Tool request violated the safe execution boundary."""


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {}

    def register(self, definition: ToolDefinition, handler: Callable[[dict[str, object]], dict[str, object]]) -> None:
        _validate_tool_name(definition.name)
        if definition.name in self._definitions:
            raise ValueError(f"duplicate tool registration: {definition.name}")
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ToolSecurityError(f"unknown tool: {name}") from exc

    def handler(self, name: str) -> Callable[[dict[str, object]], dict[str, object]]:
        self.get(name)
        return self._handlers[name]

    def list(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))


class SQLiteToolAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, record: ToolAuditRecord) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO llm_tool_audit(audit_id, tool_name, status, risk_level, request_json, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.audit_id, record.tool_name, record.status, record.risk_level, dumps_json(record.request), dumps_json(record.result), record.created_at),
            )

    def list(self, *, tool_name: str | None = None) -> tuple[ToolAuditRecord, ...]:
        if tool_name is None:
            rows = self._connection.execute("SELECT audit_id, tool_name, status, risk_level, request_json, result_json, created_at FROM llm_tool_audit ORDER BY created_at, audit_id").fetchall()
        else:
            rows = self._connection.execute("SELECT audit_id, tool_name, status, risk_level, request_json, result_json, created_at FROM llm_tool_audit WHERE tool_name = ? ORDER BY created_at, audit_id", (tool_name,)).fetchall()
        return tuple(_audit_from_row(row) for row in rows)


class SafeToolExecutor:
    def __init__(self, registry: ToolRegistry, audit_repository: SQLiteToolAuditRepository | None = None) -> None:
        self._registry = registry
        self._audit = audit_repository

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            definition = self._registry.get(request.tool_name)
            _validate_arguments(definition, request.arguments)
            _enforce_policy(definition, request)
            output = self._registry.handler(request.tool_name)(dict(request.arguments))
            result = ToolResult(request.tool_name, "success", output)
        except Exception as exc:  # noqa: BLE001 - denied tool calls must be auditable.
            result = ToolResult(request.tool_name, "denied", {"error_type": exc.__class__.__name__, "message": str(exc)}, warnings=("tool denied",))
        self._append_audit(request, result)
        return result

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._registry.list()

    def assistant_tool_definitions(self) -> tuple[AssistantToolDefinition, ...]:
        return tuple(_assistant_tool_definition(definition) for definition in self._registry.list() if definition.risk_level is ToolRiskLevel.READ_ONLY)

    def _append_audit(self, request: ToolRequest, result: ToolResult) -> None:
        if self._audit is None:
            return
        try:
            risk = self._registry.get(request.tool_name).risk_level.value
        except ToolSecurityError:
            risk = ToolRiskLevel.PROHIBITED.value
        self._audit.append(
            ToolAuditRecord(
                audit_id=f"tool-audit:{uuid4().hex}",
                tool_name=request.tool_name,
                status=result.status,
                risk_level=risk,
                request={"tool_name": request.tool_name, "arguments": _redact(request.arguments), "requested_by": request.requested_by},
                result={"status": result.status, "output": _redact(result.output), "warnings": list(result.warnings)},
                created_at=request.requested_at,
            )
        )


def default_tool_registry(connection: sqlite3.Connection) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("runtime_status", "Read runtime database schema and availability.", ToolRiskLevel.READ_ONLY),
        lambda _args: _runtime_status(connection),
    )
    registry.register(
        ToolDefinition("champion_status", "Read active champion registry slot.", ToolRiskLevel.READ_ONLY, allowed_args=("slot",)),
        lambda args: _champion_status(connection, str(args.get("slot", "default"))),
    )
    registry.register(
        ToolDefinition("v5_pipeline_history", "Read recent v5 pipeline runs.", ToolRiskLevel.READ_ONLY, allowed_args=("limit",)),
        lambda args: _v5_pipeline_history(connection, int(args.get("limit", 5))),
    )
    registry.register(
        ToolDefinition("web_search", "Read normalized external web research fixture results with citations.", ToolRiskLevel.READ_ONLY, required_args=("query",), allowed_args=("max_results",)),
        lambda args: ExternalResearchTool().search(str(args["query"]), max_results=int(args.get("max_results", 5))),
    )
    registry.register(
        ToolDefinition("news_search", "Read normalized external news fixture results with citations.", ToolRiskLevel.READ_ONLY, required_args=("query",), allowed_args=("max_results",)),
        lambda args: structured_data("news_search", args),
    )
    registry.register(
        ToolDefinition("weather_current", "Read current weather from a configured read-only provider.", ToolRiskLevel.READ_ONLY, allowed_args=("location",)),
        lambda args: structured_data("weather_current", args),
    )
    registry.register(
        ToolDefinition("weather_forecast", "Read weather forecast from a configured read-only provider.", ToolRiskLevel.READ_ONLY, allowed_args=("location",)),
        lambda args: structured_data("weather_forecast", args),
    )
    registry.register(
        ToolDefinition("exchange_rate", "Read exchange-rate data from a configured read-only provider.", ToolRiskLevel.READ_ONLY, allowed_args=("base", "quote")),
        lambda args: structured_data("exchange_rate", args),
    )
    registry.register(
        ToolDefinition("market_data", "Read market data from a configured read-only provider.", ToolRiskLevel.READ_ONLY, allowed_args=("symbol",)),
        lambda args: structured_data("market_data", args),
    )
    registry.register(
        ToolDefinition("krx_market_data", "Read fixture-backed KRX OHLC, volume, value, market cap, investor flow, program and short-sale data.", ToolRiskLevel.READ_ONLY, allowed_args=("symbol", "days")),
        lambda args: KRXMarketDataTool().fetch(symbol=str(args.get("symbol", "KOSPI")), days=int(args.get("days", 20))),
    )
    return registry


def _runtime_status(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    return {"schema_version": int(row[0]) if row else None, "ready": row is not None}


def _champion_status(connection: sqlite3.Connection, slot: str) -> dict[str, object]:
    row = connection.execute("SELECT active_version_id, payload_json, updated_at FROM champion_registry WHERE slot = ?", (slot,)).fetchone()
    if row is None:
        return {"slot": slot, "active": False}
    payload = loads_json(str(row[1]))
    return {
        "slot": slot,
        "active": True,
        "active_version_id": str(row[0]),
        "strategy_ref": str(payload.get("strategy_ref", "")),
        "fingerprint": str(payload.get("fingerprint", "")),
        "revision": int(payload.get("revision", 0)),
        "updated_at": str(row[2]),
    }


def _v5_pipeline_history(connection: sqlite3.Connection, limit: int) -> dict[str, object]:
    if limit < 1 or limit > 20:
        raise ToolSecurityError("limit must be between 1 and 20")
    rows = connection.execute(
        "SELECT run_id, status, current_stage, updated_at FROM gaon_v5_pipeline_runs ORDER BY updated_at DESC, run_id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"runs": [{"run_id": str(row[0]), "status": str(row[1]), "current_stage": str(row[2]), "updated_at": str(row[3])} for row in rows]}


def _validate_tool_name(name: str) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name) is None:
        raise ValueError("tool name must be a safe identifier")
    prohibited = ("shell", "sql", "broker", "kis", "order", "approval", "secret", "env")
    if any(token in name for token in prohibited):
        raise ToolSecurityError("prohibited tool name")


def _validate_arguments(definition: ToolDefinition, arguments: dict[str, object]) -> None:
    allowed = set(definition.allowed_args) | set(definition.required_args)
    missing = [arg for arg in definition.required_args if arg not in arguments]
    if missing:
        raise ToolSecurityError(f"missing required tool arguments: {','.join(missing)}")
    unexpected = [arg for arg in arguments if arg not in allowed]
    if unexpected:
        raise ToolSecurityError(f"unexpected tool arguments: {','.join(unexpected)}")


def _enforce_policy(definition: ToolDefinition, request: ToolRequest) -> None:
    if definition.risk_level is ToolRiskLevel.PROHIBITED:
        raise ToolSecurityError("prohibited tool cannot be executed")
    if definition.risk_level is ToolRiskLevel.APPROVAL_REQUIRED and request.approval_ref is None:
        raise ToolSecurityError("approval required tool requires approval_ref")
    if definition.risk_level is not ToolRiskLevel.READ_ONLY:
        raise ToolSecurityError("only read-only tools are enabled for the conversational release")


def _redact(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if any(token in key.casefold() for token in ("token", "secret", "key", "password")):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _audit_from_row(row: tuple[object, ...]) -> ToolAuditRecord:
    return ToolAuditRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3]), loads_json(str(row[4])), loads_json(str(row[5])), str(row[6]))


def _assistant_tool_definition(definition: ToolDefinition) -> AssistantToolDefinition:
    properties = {name: {"type": "string"} for name in definition.allowed_args + definition.required_args}
    if definition.name == "v5_pipeline_history":
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": 20}
    parameters: dict[str, object] = {"type": "object", "properties": properties, "additionalProperties": False}
    if definition.required_args:
        parameters["required"] = list(definition.required_args)
    return AssistantToolDefinition(definition.name, definition.description, parameters)
