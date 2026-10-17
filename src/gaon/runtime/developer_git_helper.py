"""Root-side narrow GitHub helper for Gaon's isolated developer worktrees.

The helper exposes exactly two actions over a local Unix socket: push the
already-created ``gaon-dev/<task>`` branch, and create a PR from that branch
to ``main``. It cannot merge PRs, checkout or update production code, deploy,
control services, touch trading state, or execute caller-provided commands.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Mapping

SOCKET_PATH = Path(os.environ.get("GAON_DEVELOPER_GIT_SOCKET", "/run/strategylab/gaon-dev-git.sock"))
WORKTREE_ROOT = Path(os.environ.get("GAON_DEVELOPER_WORKTREE_ROOT", "/var/lib/strategylab/dev_worktrees")).resolve()
EXPECTED_REMOTE = os.environ.get("GAON_DEVELOPER_REMOTE_URL", "https://github.com/Choi0211/StrategyLab-v2.git").strip()
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_REQUEST_BYTES = 20_000
MAX_OUTPUT_CHARS = 20_000


def _run(args: list[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/root",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(cwd),
        },
    )


def _task(value: object) -> str:
    task = str(value or "").strip().lower()
    if not TASK_RE.fullmatch(task):
        raise ValueError("invalid task_id")
    return task


def _worktree(task: str) -> Path:
    path = (WORKTREE_ROOT / task).resolve(strict=False)
    try:
        path.relative_to(WORKTREE_ROOT)
    except ValueError as exc:
        raise PermissionError("worktree escaped authorized root") from exc
    if not path.is_dir():
        raise FileNotFoundError("developer worktree not found")
    return path


def _verify_repo(path: Path, task: str) -> str:
    branch = f"gaon-dev/{task}"
    current = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path, timeout=15)
    if current.returncode != 0 or current.stdout.strip() != branch:
        raise PermissionError("worktree branch mismatch")
    remote = _run(["git", "remote", "get-url", "origin"], cwd=path, timeout=15)
    if remote.returncode != 0 or remote.stdout.strip() != EXPECTED_REMOTE:
        raise PermissionError("developer remote mismatch")
    return branch


def _push(path: Path, branch: str) -> dict[str, object]:
    proc = _run(
        ["git", "-c", "credential.helper=!/usr/bin/gh auth git-credential", "push", "-u", "origin", branch],
        cwd=path,
        timeout=180,
    )
    return {"ok": proc.returncode == 0, "action": "push", "branch": branch, "output": proc.stdout[-MAX_OUTPUT_CHARS:]}


def _create_pr(path: Path, branch: str, request: Mapping[str, object]) -> dict[str, object]:
    title = str(request.get("title") or "").strip()[:160]
    body = str(request.get("body") or "").strip()[:6000]
    if len(title) < 3:
        raise ValueError("PR title required")
    proc = _run(
        ["/usr/bin/gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body or "Gaon isolated developer-agent change for human review."],
        cwd=path,
        timeout=180,
    )
    return {"ok": proc.returncode == 0, "action": "create_pr", "branch": branch, "output": proc.stdout[-MAX_OUTPUT_CHARS:]}


def handle_request(request: Mapping[str, object]) -> dict[str, object]:
    action = str(request.get("action") or "").strip()
    if action not in {"push", "create_pr"}:
        raise PermissionError("unsupported helper action")
    task = _task(request.get("task_id"))
    path = _worktree(task)
    branch = _verify_repo(path, task)
    result = _push(path, branch) if action == "push" else _create_pr(path, branch, request)
    result.update({
        "task_id": task,
        "production_tree_mutated": False,
        "main_merged": False,
        "deployed": False,
        "systemd_controlled": False,
        "trading_executed": False,
    })
    return result


def _read_request(conn: socket.socket) -> Mapping[str, object]:
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_REQUEST_BYTES:
        chunk = conn.recv(min(4096, MAX_REQUEST_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if b"\n" in chunk:
            break
    if total > MAX_REQUEST_BYTES:
        raise ValueError("request too large")
    raw = b"".join(chunks).split(b"\n", 1)[0]
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    return payload


def serve(path: Path = SOCKET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        gid = grp.getgrnam("strategylab").gr_gid
        os.chown(path, 0, gid)
        os.chmod(path, 0o660)
        server.listen(8)
        while True:
            conn, _addr = server.accept()
            with conn:
                try:
                    result = handle_request(_read_request(conn))
                except Exception as exc:  # noqa: BLE001 - helper must fail closed and return no traceback/secrets.
                    result = {"ok": False, "error_type": exc.__class__.__name__, "message": str(exc)[:500]}
                conn.sendall((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=str(SOCKET_PATH))
    args = parser.parse_args()
    serve(Path(args.socket))


if __name__ == "__main__":
    main()
