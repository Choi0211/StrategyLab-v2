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

File-backed runtimes use bounded request workers with a SQLite connection
created and closed in each worker. Chat execution remains serialized with
nonblocking admission, while health/read requests can finish independently.
In-memory runtimes retain the single-threaded server. Browser identity is
conversation scoping, not authentication; this is not a public multi-tenant API.

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
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from socketserver import ThreadingMixIn
from threading import BoundedSemaphore
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from gaon.knowledge.research_mission import ResearchMission, candidate_records, get_candidate
from gaon.knowledge.strategy_candidate import (
    StrategyCandidateRecord,
    evaluate_economic_viability,
    next_blocker_driven_research_action,
)
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

_CANDIDATE_DETAIL_PATH = re.compile(r"^/gaon/research/candidates/(?P<candidate_id>[^/]+)$")

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

# deploy/scripts/storage_lifecycle_manager.py lives outside the installable
# `gaon` package (deploy/ is deployment tooling, not application code), so
# GET /gaon/storage/status reuses it via subprocess --report rather than
# importing it or duplicating its HOT/WARM/COLD classification logic here -
# one source of truth for what counts as HOT/WARM/COLD. --report is
# documented (in that script's own module docstring) as read-only and safe
# to run at any time.
_STORAGE_LIFECYCLE_SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "storage_lifecycle_manager.py"
STORAGE_STATUS_TIMEOUT_SECONDS = 15


def _default_storage_root_paths() -> list[str]:
    raw = os.environ.get("GAON_STORAGE_ROOT_PATHS", "")
    paths = [p.strip() for p in raw.split(",") if p.strip()]
    return paths or ["/var/lib/strategylab", "/opt/strategylab-v2"]


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
        self._repository = repository
        self._brain = LLMConversationBrain(
            config,
            repository,
            context_orchestrator=context,
            tool_executor=SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection)),
            tool_result_repository=SQLiteConversationToolResultRepository(connection),
            event_store=SQLiteEventStore(connection),
            metrics=self._metrics,
        )

    def mission_for(self, session_ref: str) -> ResearchMission | None:
        """Read-only: the ResearchMission (if any) persisted for this
        session. A mission is scoped to the conversation session that
        created it - there is no single global "the" mission - so this
        mirrors exactly how gaon.runtime.llm_conversation.
        LLMConversationBrain._mission_for reads it (same repository, same
        session metadata key, same ResearchMission.from_json), just
        exposed as a public, testable read for the HTTP layer. Never
        writes anything."""
        session_id = f"web:{session_ref}"
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return None
        root = session.metadata.get("conversation_mvp")
        if not isinstance(root, dict):
            return None
        raw = root.get("research_mission")
        if not isinstance(raw, dict):
            return None
        try:
            return ResearchMission.from_json(raw)
        except (KeyError, ValueError, TypeError):
            return None

    def handle(
        self,
        *,
        message: str,
        session_ref: str,
        user_ref: str,
        read_only: bool,
        received_at: str,
        structured_context: Mapping[str, object] | None = None,
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
                    structured_context=structured_context,
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
    split = urlsplit(path)
    route_path = split.path
    query = parse_qs(split.query)

    if method == "GET" and route_path == "/":
        return 200, {
            "schema_version": WEB_API_SCHEMA_VERSION,
            "service": "Gaon Web API",
            "status": "ok",
            "health": "/gaon/health",
            "chat": "/gaon/chat",
            "research_mission": "/gaon/research/mission",
            "storage_status": "/gaon/storage/status",
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
            "approval_bypassed": False,
        }
    if method == "GET" and route_path == "/gaon/health":
        return 200, {"schema_version": WEB_API_SCHEMA_VERSION, "status": "ok"}
    if method == "POST" and route_path == "/gaon/chat":
        if not isinstance(body, Mapping) or not str(body.get("message", "")).strip():
            return 400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "message is required"}
        session_ref = str(body.get("session_ref") or uuid4().hex)
        user_ref = str(body.get("user_ref") or session_ref)
        read_only = bool(body.get("read_only", False))
        received_at = _utc_now()
        extras = {}
        if isinstance(body.get("structured_context"), dict):
            extras["structured_context"] = body["structured_context"]
        payload = adapter.handle(
            message=str(body["message"]),
            session_ref=session_ref,
            user_ref=user_ref,
            read_only=read_only,
            received_at=received_at,
            **extras,
        )
        return 200, payload
    if method == "GET" and route_path == "/gaon/research/mission":
        return _handle_mission_status(adapter, query)
    if method == "GET" and route_path == "/gaon/research/candidates":
        return _handle_candidates_list(adapter, query)
    detail_match = _CANDIDATE_DETAIL_PATH.match(route_path)
    if method == "GET" and detail_match:
        return _handle_candidate_detail(adapter, query, detail_match.group("candidate_id"))
    if method == "GET" and route_path == "/gaon/storage/status":
        return _handle_storage_status()
    return 404, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "not found"}


def _session_ref_from_query(query: Mapping[str, list[str]]) -> str | None:
    values = query.get("session_ref")
    if not values or not values[0].strip():
        return None
    return values[0].strip()


def _mission_payload(mission: ResearchMission | None) -> Mapping[str, object]:
    if mission is None:
        return {"schema_version": WEB_API_SCHEMA_VERSION, "exists": False}
    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        "exists": True,
        "mission_id": mission.mission_id,
        "market": mission.market,
        "status": mission.status.value,
        "progress_label": mission.progress_label,
        "target_promotion_ready_candidates": mission.target_promotion_ready_candidates,
        "current_promotion_ready_candidates": mission.current_promotion_ready_candidates,
        "active_candidate_id": mission.active_candidate_id,
        "candidate_count": len(mission.candidates),
        "cycles_completed": mission.cycles_completed,
        "blocked_reason": mission.blocked_reason,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }


def _candidate_payload(candidate: StrategyCandidateRecord) -> Mapping[str, object]:
    """Pure read of already-persisted candidate state, plus two cheap
    deterministic derivations (both pure functions over that same
    persisted evidence, no I/O, no new research): the economic-viability
    verdict and the next blocker-driven action - the same two functions
    gaon.knowledge.strategy_candidate already uses internally to decide
    what happens next, exposed here read-only for a status UI."""
    viability = evaluate_economic_viability(candidate)
    next_action, next_action_reason = next_blocker_driven_research_action(candidate)
    return {
        "candidate_id": candidate.candidate_id,
        "strategy_fingerprint": candidate.strategy_fingerprint,
        "strategy_family": candidate.strategy_family,
        "status": candidate.status.value,
        "validation_stage_status": dict(candidate.validation_stage_status),
        "economic_viability": {"status": viability.status.value, "reason": viability.reason},
        "next_action": next_action,
        "next_action_reason": next_action_reason,
        "trade_count": candidate.trade_count,
        "attempted_symbols": candidate.attempted_symbols,
        "valid_symbols": candidate.valid_symbols,
        "rejected_reason": candidate.rejected_reason,
        "promotion_ready_at": candidate.promotion_ready_at,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }


def _handle_mission_status(adapter: GaonWebChatAdapter, query: Mapping[str, list[str]]) -> tuple[int, Mapping[str, object]]:
    session_ref = _session_ref_from_query(query)
    if session_ref is None:
        return 400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "session_ref query parameter is required"}
    mission = adapter.mission_for(session_ref)
    return 200, {
        **_mission_payload(mission),
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }


def _handle_candidates_list(adapter: GaonWebChatAdapter, query: Mapping[str, list[str]]) -> tuple[int, Mapping[str, object]]:
    session_ref = _session_ref_from_query(query)
    if session_ref is None:
        return 400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "session_ref query parameter is required"}
    mission = adapter.mission_for(session_ref)
    candidates = [] if mission is None else [_candidate_payload(c) for c in candidate_records(mission)]
    return 200, {
        "schema_version": WEB_API_SCHEMA_VERSION,
        "exists": mission is not None,
        "mission_id": mission.mission_id if mission is not None else None,
        "candidates": candidates,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }


def _handle_candidate_detail(
    adapter: GaonWebChatAdapter, query: Mapping[str, list[str]], candidate_id: str
) -> tuple[int, Mapping[str, object]]:
    session_ref = _session_ref_from_query(query)
    if session_ref is None:
        return 400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "session_ref query parameter is required"}
    mission = adapter.mission_for(session_ref)
    candidate = None if mission is None else get_candidate(mission, candidate_id)
    if candidate is None:
        return 404, {"schema_version": WEB_API_SCHEMA_VERSION, "exists": False, "error": "candidate not found"}
    return 200, {
        "schema_version": WEB_API_SCHEMA_VERSION,
        "exists": True,
        "mission_id": mission.mission_id,
        **_candidate_payload(candidate),
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }


def _handle_storage_status() -> tuple[int, Mapping[str, object]]:
    """Runs storage_lifecycle_manager.py --report (read-only, per that
    script's own contract) as a subprocess and relays its JSON report.
    Never raises out to the caller - a missing script, a bad exit code, or
    unparsable output all degrade to a well-shaped error response rather
    than a 500 or an unhandled exception, matching this module's existing
    failure-isolation pattern for /gaon/chat."""
    if not _STORAGE_LIFECYCLE_SCRIPT.exists():
        return 502, {
            "schema_version": WEB_API_SCHEMA_VERSION,
            "error": f"storage_lifecycle_manager.py not found at {_STORAGE_LIFECYCLE_SCRIPT}",
        }
    cmd = [sys.executable, str(_STORAGE_LIFECYCLE_SCRIPT), "--report", *_default_storage_root_paths_argv()]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=STORAGE_STATUS_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 502, {"schema_version": WEB_API_SCHEMA_VERSION, "error": f"could not run storage_lifecycle_manager.py: {exc}"}
    if result.returncode != 0:
        return 502, {
            "schema_version": WEB_API_SCHEMA_VERSION,
            "error": "storage_lifecycle_manager.py --report exited non-zero",
            "stderr": result.stderr.strip()[-2000:],
        }
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return 502, {"schema_version": WEB_API_SCHEMA_VERSION, "error": f"storage_lifecycle_manager.py output was not valid JSON: {exc}"}
    return 200, report


def _default_storage_root_paths_argv() -> list[str]:
    argv: list[str] = []
    for root in _default_storage_root_paths():
        argv.extend(["--root", root])
    return argv


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_request_handler(adapter: GaonWebChatAdapter | None, *, adapter_factory=None) -> type[BaseHTTPRequestHandler]:
    """Builds a BaseHTTPRequestHandler subclass bound to one adapter
    instance via closure - kept separate from dispatch_request so the
    dispatch contract itself stays testable without a socket."""

    chat_slot = BoundedSemaphore(1)

    class _Handler(BaseHTTPRequestHandler):
        server_version = "GaonWebAPI/1"

        def _dispatch(self, method, body):
            is_chat = method == "POST" and urlsplit(self.path).path == "/gaon/chat"
            if is_chat and not chat_slot.acquire(blocking=False):
                return 503, {"error": "conversation_busy", "text": "다른 대화를 처리 중입니다. 잠시 후 다시 요청해주세요."}
            try:
                if adapter_factory is None:
                    return dispatch_request(adapter, method=method, path=self.path, body=body)
                with adapter_factory() as scoped_adapter:
                    return dispatch_request(scoped_adapter, method=method, path=self.path, body=body)
            finally:
                if is_chat:
                    chat_slot.release()

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
            status, payload = self._dispatch("GET", None)
            self._write(status, payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._write(400, {"error": "invalid request body size"})
                return
            if length <= 0 or length > MAX_REQUEST_BODY_BYTES:
                self._write(400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "invalid request body size"})
                return
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write(400, {"schema_version": WEB_API_SCHEMA_VERSION, "error": "invalid JSON body"})
                return
            status, payload = self._dispatch("POST", body)
            self._write(status, payload)

    return _Handler


class BoundedWebServer(ThreadingMixIn, HTTPServer):
    """Reject overload; never share a SQLite connection across worker threads."""
    daemon_threads = False

    def __init__(self, address, handler):
        self._slots = BoundedSemaphore(4)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        request.settimeout(45)
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def build_server(config, store, *, host=DEFAULT_HOST, port=DEFAULT_PORT):
    if store.path == ":memory:":
        return HTTPServer((host, port), build_request_handler(GaonWebChatAdapter(config, store._connection)))

    @contextmanager
    def scoped_adapter():
        connection = sqlite3.connect(store.path, timeout=5)
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield GaonWebChatAdapter(config, connection)
        finally:
            connection.close()

    return BoundedWebServer((host, port), build_request_handler(None, adapter_factory=scoped_adapter))


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
    bind_host = host or DEFAULT_HOST
    bind_port = port or DEFAULT_PORT
    httpd = build_server(config, store, host=bind_host, port=bind_port)
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


def production_gaon_research_status_api_release_check() -> Mapping[str, object]:
    """Regression guard for the read-only KR research-status endpoints
    (/gaon/research/mission, /gaon/research/candidates,
    /gaon/research/candidates/<id>): with a real ResearchMission +
    StrategyCandidateRecord persisted through the SAME production
    functions research_mission.py/strategy_candidate.py already use
    everywhere else (never fabricated JSON), the endpoints return the
    correct data; against an empty database (no session for this
    session_ref at all) they return well-shaped empty responses rather
    than erroring; a missing session_ref is rejected with 400; an
    unknown candidate_id is 404; every response still carries the
    standard non-mutation invariants."""
    from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, next_candidate_sequence
    from gaon.knowledge.strategy_candidate import new_candidate
    from gaon.runtime.llm_conversation import LLMConversationSession

    now = "2026-08-23T00:00:00Z"
    store = RuntimeStateStore(":memory:")
    try:
        config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
        adapter = GaonWebChatAdapter(config, store._connection)

        empty_mission_status, empty_mission_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/mission?session_ref=release-check", body=None
        )
        empty_candidates_status, empty_candidates_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates?session_ref=release-check", body=None
        )
        missing_session_ref_status, _ = dispatch_request(
            adapter, method="GET", path="/gaon/research/mission", body=None
        )

        # A real chat turn creates the session row, exactly as any real
        # caller would trigger it.
        adapter.handle(
            message="가온 상태 알려줘 readonly", session_ref="release-check", user_ref="release-check-user",
            read_only=True, received_at=now,
        )

        # Seed a real mission + real candidate through the SAME production
        # functions used everywhere else in this codebase (not a parallel
        # storage mechanism), then persist it into the session exactly the
        # way LLMConversationBrain._remember_mission does (same
        # repository, same session metadata key) - this is test setup via
        # the real write path, not fabricated JSON handed to the reader.
        mission = extract_or_update_mission(
            "대한민국 장에 맞는 단타 매매 전략을 연구해줘. 승격 준비 후보 3개가 준비될 때까지 계속해줘.",
            existing=None, now=now,
        )
        candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=now)
        mission = add_candidate(mission, candidate, now=now)

        session = adapter._repository.get_session("web:release-check")
        metadata = dict(session.metadata)
        metadata["conversation_mvp"] = {"research_mission": mission.to_json()}
        adapter._repository.upsert_session(
            LLMConversationSession(
                session.session_id, session.user_ref, session.source, session.status,
                session.created_at, now, metadata,
            )
        )

        mission_status, mission_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/mission?session_ref=release-check", body=None
        )
        candidates_status, candidates_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates?session_ref=release-check", body=None
        )
        detail_status, detail_payload = dispatch_request(
            adapter, method="GET",
            path=f"/gaon/research/candidates/{candidate.candidate_id}?session_ref=release-check", body=None,
        )
        missing_detail_status, _ = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates/NOT-REAL?session_ref=release-check", body=None,
        )
    finally:
        store.close()

    candidates_list = candidates_payload.get("candidates", [])
    checks = {
        "empty_mission_status_ok": empty_mission_status == 200,
        "empty_mission_not_exists": empty_mission_payload.get("exists") is False,
        "empty_candidates_status_ok": empty_candidates_status == 200,
        "empty_candidates_list_is_empty": empty_candidates_payload.get("candidates") == [],
        "missing_session_ref_is_400": missing_session_ref_status == 400,
        "mission_status_ok": mission_status == 200,
        "mission_exists": mission_payload.get("exists") is True,
        "mission_progress_label_correct": mission_payload.get("progress_label") == "0/3",
        "mission_candidate_count_correct": mission_payload.get("candidate_count") == 1,
        "candidates_status_ok": candidates_status == 200,
        "candidates_list_has_one": len(candidates_list) == 1,
        "candidate_id_matches": bool(candidates_list) and candidates_list[0].get("candidate_id") == candidate.candidate_id,
        "candidate_has_validation_stage_status": bool(candidates_list) and "validation_stage_status" in candidates_list[0],
        "detail_status_ok": detail_status == 200,
        "detail_candidate_id_matches": detail_payload.get("candidate_id") == candidate.candidate_id,
        "detail_has_economic_viability": "economic_viability" in detail_payload,
        "missing_detail_is_404": missing_detail_status == 404,
        "no_strategy_mutation": mission_payload.get("strategy_mutated") is False and detail_payload.get("strategy_mutated") is False,
        "no_order_execution": mission_payload.get("order_executed") is False and detail_payload.get("order_executed") is False,
        "no_champion_promotion": mission_payload.get("champion_promoted") is False and detail_payload.get("champion_promoted") is False,
        "no_approval_bypass": mission_payload.get("approval_bypassed") is False and detail_payload.get("approval_bypassed") is False,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"gaon research status api release check failed: {failed}")

    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        **checks,
        "sample_progress_label": mission_payload.get("progress_label"),
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def production_gaon_storage_status_api_release_check() -> Mapping[str, object]:
    """Regression guard for GET /gaon/storage/status: proves it actually
    runs the real deploy/scripts/storage_lifecycle_manager.py --report
    subprocess (against a temp directory tree it builds itself, not the
    real /var/lib/strategylab - this check must be runnable on a dev
    machine with none of that present) and relays a well-shaped report,
    and separately proves the endpoint degrades gracefully (a clear error,
    not a crash) when the script path doesn't exist."""
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "strategylab"
        sibling_root = Path(tmp) / "binance-trading"
        (root / "backups").mkdir(parents=True)
        sibling_root.mkdir(parents=True)
        (root / "backups" / "sample.bak").write_bytes(b"sample backup content")

        original_default = _default_storage_root_paths
        original_script = globals()["_STORAGE_LIFECYCLE_SCRIPT"]
        try:
            globals()["_default_storage_root_paths"] = lambda: [str(root), str(sibling_root)]
            status, payload = _handle_storage_status()
        finally:
            globals()["_default_storage_root_paths"] = original_default

        # Second call: script path deliberately pointed at nothing, proving
        # the endpoint returns a clean error instead of raising.
        try:
            globals()["_STORAGE_LIFECYCLE_SCRIPT"] = Path(tmp) / "does-not-exist.py"
            missing_status, missing_payload = _handle_storage_status()
        finally:
            globals()["_STORAGE_LIFECYCLE_SCRIPT"] = original_script

    checks = {
        "report_status_ok": status == 200,
        "report_has_tier_bytes": isinstance(payload.get("tier_bytes"), dict),
        "report_has_disk_usage": isinstance(payload.get("disk_usage"), dict),
        "report_has_filesystem_usage": isinstance(payload.get("filesystem_usage"), list),
        "same_filesystem_deduped": isinstance(payload.get("filesystem_usage"), list) and len(payload["filesystem_usage"]) == 1,
        "report_never_destructive": payload.get("destructive_action_taken") is False,
        "missing_script_is_clean_error": missing_status == 502 and "error" in missing_payload,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"gaon storage status api release check failed: {failed}")

    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        **checks,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def production_gaon_web_api_root_release_check() -> Mapping[str, object]:
    """Regression guard for the Gaon API root behind :8443.

    GET / is service discovery only. It must make the API look healthy
    without running chat, research, approval, storage cleanup, orders, or
    strategy mutation.
    """
    store = RuntimeStateStore(":memory:")
    try:
        adapter = GaonWebChatAdapter(GaonRuntimeConfig(), store._connection)
        status, payload = dispatch_request(adapter, method="GET", path="/", body=None)
    finally:
        store.close()
    checks = {
        "root_status_ok": status == 200,
        "service_named": payload.get("service") == "Gaon Web API",
        "health_linked": payload.get("health") == "/gaon/health",
        "chat_linked": payload.get("chat") == "/gaon/chat",
        "strategy_mutated_false": payload.get("strategy_mutated") is False,
        "order_executed_false": payload.get("order_executed") is False,
        "approval_bypassed_false": payload.get("approval_bypassed") is False,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"gaon web api root release check failed: {failed}")
    return {
        "schema_version": WEB_API_SCHEMA_VERSION,
        **checks,
        "service": payload.get("service"),
        "strategy_mutated": False,
        "order_executed": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
