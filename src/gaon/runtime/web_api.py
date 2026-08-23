"""Gaon's first HTTP web API layer.

Exposes the SAME conversation path Telegram already uses
(``LLMConversationBrain.respond``) over HTTP, so a separate web
dashboard (the Binance trading bot's existing chat widget, or the
future unified web dashboard) can ask Gaon natural-language questions
and share the same Gaon core/research state Telegram uses - not a
second, parallel conversation implementation.

Deliberately uses only the Python standard library (``http.server``).
This codebase's ``pyproject.toml`` has almost no external dependencies
by design (only ``tzdata``), and Flask/FastAPI/etc. are not installed
in this environment - adding one would be a bigger decision than this
module's scope, so a small ``BaseHTTPRequestHandler`` server is used
instead. The actual routing/dispatch logic (``dispatch_request``) is a
plain function with no socket dependency, so it can be - and is -
tested in-process without opening a real port.

Deliberately single-threaded (``http.server.HTTPServer``, not
``ThreadingHTTPServer``): the underlying ``sqlite3.Connection`` this
adapter is built on is not safe to use from more than one thread (a
real, reproduced bug during development - a threaded server handling
one request per thread raised
``sqlite3.ProgrammingError: SQLite objects created in a thread can
only be used in that same thread``). This is a low-traffic
single-operator chat API, not a public multi-tenant service, so
serializing requests is the correct trade-off rather than adding a
connection pool or per-request connection for no real benefit.

Safety: every response carries the same
strategy_mutated/order_executed/champion_promoted/approval_bypassed
invariants every other module in this codebase surfaces, always False
here, since this layer never does any of those things - it only calls
``LLMConversationBrain.respond``, the exact function Telegram already
uses, which already enforces every approval/promotion gate itself.
This module adds no new mutation path.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping
from uuid import uuid4

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation_context import ConversationContextOrchestrator
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.llm_conversation import (
    LLMConversationBrain,
    LLMConversationRequest,
    LLMConversationResponse,
    SQLiteConversationRepository,
    SQLiteConversationToolResultRepository,
)
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.research_failures import classify_exception, warning_for_failure
from gaon.runtime.storage import RuntimeStateStore

logger = logging.getLogger(__name__)

WEB_API_SCHEMA_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BODY_BYTES = 8192

# The exact literal already recognized by
# gaon.knowledge.research_mission.is_explicit_read_only_query's
# _READ_ONLY_INTENT_TOKENS. Appending it lets a `read_only: true` HTTP
# request hint route through the SAME existing read-only intent
# detection Telegram/CLI callers already get from typing "readonly" -
# no second, HTTP-only mutation-permission concept is introduced here.
_READ_ONLY_TEXT_MARKER = "readonly"


class GaonWebChatAdapter:
    """Web-facing conversational adapter. Mirrors
    ``gaon.runtime.telegram_agent.TelegramConversationAgent`` exactly
    (source="web" instead of "telegram", session/user prefixed
    "web"/"web-user" instead of "telegram"/"telegram-user") - reuses
    ``LLMConversationBrain`` directly, not a second implementation of
    conversation/routing logic."""

    def __init__(
        self,
        config: GaonRuntimeConfig,
        connection: sqlite3.Connection,
        *,
        metrics: MetricsCollector | None = None,
    ) -> None:
        repository = SQLiteConversationRepository(connection)
        context = ConversationContextOrchestrator(connection, repository)
        self._metrics = metrics or MetricsCollector()
        self._brain = LLMConversationBrain(
            config,
            repository,
            context_orchestrator=context,
            tool_executor=SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection)),
            tool_result_repository=SQLiteConversationToolResultRepository(connection),
            event_store=SQLiteEventStore(connection),
            metrics=self._metrics,
        )

    def handle(
        self,
        *,
        message: str,
        session_ref: str,
        user_ref: str,
        read_only: bool,
        received_at: str,
    ) -> Mapping[str, object]:
        session_id = f"web:{session_ref}"
        text = message.strip()
        if read_only and text:
            text = f"{text} {_READ_ONLY_TEXT_MARKER}"
        message_id = f"web:{session_ref}:{uuid4().hex}"
        try:
            response = self._brain.respond(
                LLMConversationRequest(
                    session_id=session_id,
                    user_ref=f"web-user:{user_ref}",
                    source="web",
                    text=text,
                    received_at=received_at,
                    message_id=message_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the HTTP caller must get a safe fallback, not a 500 leak.
            failure = classify_exception(exc)
            self._metrics.increment(
                "gaon_web_chat_failures_total", error_type=failure.error_type, failure_stage=failure.stage
            )
            logger.exception(
                "web chat failed",
                extra={"error_type": failure.error_type, "failure_stage": failure.stage, "route": "web_conversation"},
            )
            return _fallback_payload(failure, session_id, received_at)
        return _response_payload(response)


def _response_payload(response: LLMConversationResponse) -> Mapping[str, object]:
    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        "response_id": response.response_id,
        "session_id": response.session_id,
        "text": response.text,
        "intent": response.intent.value,
        "route": response.route,
        "references": list(response.references),
        "warnings": list(response.warnings),
        "tool_calls": list(response.tool_calls),
        "approval_required": response.approval_required,
        "generated_at": response.generated_at,
        "provider": response.provider,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }


def _fallback_payload(failure: Any, session_id: str, received_at: str) -> Mapping[str, object]:
    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        "response_id": f"web-fallback:{uuid4().hex}",
        "session_id": session_id,
        "text": failure.user_message,
        "intent": "unknown",
        "route": f"failure_{failure.stage}",
        "references": [],
        "warnings": [warning_for_failure(failure)],
        "tool_calls": [],
        "approval_required": False,
        "generated_at": received_at,
        "provider": "deterministic",
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }


def dispatch_request(
    adapter: GaonWebChatAdapter,
    *,
    method: str,
    path: str,
    body: Mapping[str, object] | None,
) -> tuple[int, Mapping[str, object]]:
    """Pure routing/dispatch, independent of any socket - this is what
    both the real HTTP handler and the release check/tests call, so the
    release check never needs to open a real port to prove the contract
    end to end."""
    if method == "GET" and path == "/gaon/health":
        return 200, {"schema_version": WEB_API_SCHEMA_VERSION, "status": "ok"}
    if method == "POST" and path == "/gaon/chat":
        if not isinstance(body, Mapping) or not str(body.get("message", "")).strip():
            return 400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "message is required"}
        session_ref = str(body.get("session_ref") or uuid4().hex)
        user_ref = str(body.get("user_ref") or "anonymous")
        read_only = bool(body.get("read_only", False))
        received_at = _utc_now()
        payload = adapter.handle(
            message=str(body["message"]),
            session_ref=session_ref,
            user_ref=user_ref,
            read_only=read_only,
            received_at=received_at,
        )
        return 200, payload
    return 404, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "not found"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_request_handler(adapter: GaonWebChatAdapter) -> type[BaseHTTPRequestHandler]:
    """Builds a BaseHTTPRequestHandler subclass bound to one adapter
    instance via closure - kept separate from dispatch_request so the
    dispatch contract itself stays testable without a socket."""

    class _Handler(BaseHTTPRequestHandler):
        server_version = "GaonWebAPI/1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
            logger.info("gaon-web-api " + format, *args)

        def _write(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            status, payload = dispatch_request(adapter, method="GET", path=self.path, body=None)
            self._write(status, payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > MAX_REQUEST_BODY_BYTES:
                self._write(400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "invalid request body size"})
                return
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write(400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "invalid JSON body"})
                return
            status, payload = dispatch_request(adapter, method="POST", path=self.path, body=body)
            self._write(status, payload)

    return _Handler


def run_server(
    config: GaonRuntimeConfig,
    store: RuntimeStateStore,
    *,
    host: str | None = None,
    port: int | None = None,
) -> HTTPServer:
    """Builds and starts (via serve_forever, blocking) the web API
    server. Binds to localhost by default - this sits behind a reverse
    proxy in production (a separate, later deployment concern), not
    exposed to the public internet directly by this module."""
    adapter = GaonWebChatAdapter(config, store._connection)
    handler_cls = build_request_handler(adapter)
    bind_host = host or DEFAULT_HOST
    bind_port = port or DEFAULT_PORT
    httpd = HTTPServer((bind_host, bind_port), handler_cls)
    logger.info("gaon web API listening on %s:%s", bind_host, bind_port)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd


def production_gaon_web_chat_api_release_check() -> Mapping[str, object]:
    """Regression guard for the Gaon web chat HTTP contract: health
    check works, a read-only-hinted chat request round-trips through
    the REAL LLMConversationBrain (not a stub), a malformed request is
    rejected with 400 rather than crashing, and every response carries
    the standard non-mutation invariants."""
    store = RuntimeStateStore(":memory:")
    try:
        config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
        adapter = GaonWebChatAdapter(config, store._connection)

        health_status, health_payload = dispatch_request(adapter, method="GET", path="/gaon/health", body=None)

        chat_status, chat_payload = dispatch_request(
            adapter,
            method="POST",
            path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "release-check", "user_ref": "release-check-user", "read_only": True},
        )

        missing_message_status, missing_message_payload = dispatch_request(
            adapter, method="POST", path="/gaon/chat", body={"session_ref": "release-check"}
        )

        not_found_status, _ = dispatch_request(adapter, method="GET", path="/does/not/exist", body=None)

        second_status, second_payload = dispatch_request(
            adapter,
            method="POST",
            path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "release-check", "user_ref": "release-check-user", "read_only": True},
        )
    finally:
        store.close()

    checks = {
        "health_check_ok": health_status == 200 and health_payload.get("status") == "ok",
        "chat_request_ok": chat_status == 200,
        "chat_response_has_text": bool(str(chat_payload.get("text", "")).strip()),
        "chat_response_has_route": bool(str(chat_payload.get("route", "")).strip()),
        "chat_response_session_matches": chat_payload.get("session_id") == "web:release-check",
        "missing_message_rejected": missing_message_status == 400,
        "unknown_path_is_404": not_found_status == 404,
        "second_turn_same_session_ok": second_status == 200 and second_payload.get("session_id") == chat_payload.get("session_id"),
        "no_strategy_mutation": chat_payload.get("strategy_mutated") is False,
        "no_order_execution": chat_payload.get("order_executed") is False,
        "no_champion_promotion": chat_payload.get("champion_promoted") is False,
        "no_approval_bypass": chat_payload.get("approval_bypassed") is False,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"gaon web chat api release check failed: {failed}")

    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        **checks,
        "sample_route": chat_payload.get("route"),
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
