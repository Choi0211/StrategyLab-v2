"""Safe bounded developer-agent operations for isolated StrategyLab worktrees.

The module deliberately cannot merge main, deploy, control systemd, mutate the
production DB, touch trading services, or execute arbitrary shell commands.
Write operations require an explicit approval flow owned by the web/CLI layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Iterable
from uuid import uuid4

REPO_ROOT = Path(os.environ.get("GAON_REPOSITORY_ROOT", "/opt/strategylab-v2")).resolve()
WORKTREE_ROOT = Path(os.environ.get("GAON_DEVELOPER_WORKTREE_ROOT", "/var/lib/strategylab/dev_worktrees")).resolve()
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
MAX_READ_BYTES = 96_000
MAX_PATCH_BYTES = 250_000
MAX_TEST_OUTPUT = 30_000
_ALLOWED_TOP_LEVEL = frozenset({"src", "tests", "docs"})
_ALLOWED_ROOT_FILES = frozenset({"pyproject.toml", "README.md", ".gitignore"})
_DENIED_PARTS = frozenset({".env", ".git", "secrets", "secret", "token", "credentials", "keys"})
_TASK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_TEST_TARGET_RE = re.compile(r"^[A-Za-z0-9_./:-]+$")


@dataclass(frozen=True)
class DeveloperActionResult:
    ok: bool
    action: str
    task_id: str
    worktree: str | None = None
    branch: str | None = None
    detail: str = ""
    output: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "action": self.action,
            "task_id": self.task_id,
            "worktree": self.worktree,
            "branch": self.branch,
            "detail": self.detail,
            "output": self.output,
            "production_tree_mutated": False,
            "main_merged": False,
            "deployed": False,
            "systemd_controlled": False,
            "trading_executed": False,
        }


def _task_id(value: object) -> str:
    task = str(value or "").strip().lower()
    if not _TASK_RE.fullmatch(task):
        raise ValueError("task_id must match [a-z0-9][a-z0-9._-]{0,63}")
    return task


def _branch(task: str) -> str:
    return f"gaon-dev/{task}"


def _worktree(task: str) -> Path:
    root = WORKTREE_ROOT
    path = (root / task).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionError("developer worktree escaped authorized root") from exc
    return path


def _run(args: list[str], *, cwd: Path, timeout: int = 60, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _allowed_repo_path(raw: object, *, root: Path = REPO_ROOT) -> Path:
    rel = str(raw or "").strip().lstrip("/")
    if not rel:
        raise ValueError("path required")
    p = (root / rel).resolve(strict=False)
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise PermissionError("path escaped repository") from exc
    parts = set(p.relative_to(root).parts)
    if any(part.casefold() in _DENIED_PARTS for part in parts):
        raise PermissionError("sensitive repository path denied")
    top = p.relative_to(root).parts[0]
    if top not in _ALLOWED_TOP_LEVEL and rel not in _ALLOWED_ROOT_FILES:
        raise PermissionError("path is outside developer allowlist")
    return p


def repository_read(args: dict[str, object]) -> dict[str, object]:
    p = _allowed_repo_path(args.get("path"))
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.stat().st_size > MAX_READ_BYTES:
        raise ValueError("file too large for bounded repository read")
    raw = p.read_bytes()
    if b"\x00" in raw:
        raise ValueError("binary file not supported")
    text = raw.decode("utf-8", "replace")
    return {"path": str(p.relative_to(REPO_ROOT)), "text": text, "bytes": len(raw), "read_only": True}


def developer_status(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        return {"task_id": task, "exists": False, "branch": _branch(task), "worktree": str(path), "production_tree_mutated": False}
    proc = _run(["git", "status", "--short", "--branch"], cwd=path, timeout=15)
    return {"task_id": task, "exists": True, "branch": _branch(task), "worktree": str(path), "status": proc.stdout[:MAX_TEST_OUTPUT], "production_tree_mutated": False}


def worktree_create(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    branch = _branch(task)
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return DeveloperActionResult(True, "worktree_create", task, str(path), branch, "worktree already exists").to_json()
    # Refresh refs, then create from origin/main. No checkout in production tree.
    fetch = _run(["git", "fetch", "origin", "main"], cwd=REPO_ROOT, timeout=60)
    if fetch.returncode != 0:
        return DeveloperActionResult(False, "worktree_create", task, detail="git fetch failed", output=fetch.stdout[-MAX_TEST_OUTPUT:]).to_json()
    check = _run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=REPO_ROOT, timeout=15)
    cmd = ["git", "worktree", "add"]
    if check.returncode == 0:
        cmd += [str(path), branch]
    else:
        cmd += ["-b", branch, str(path), "origin/main"]
    proc = _run(cmd, cwd=REPO_ROOT, timeout=60)
    return DeveloperActionResult(proc.returncode == 0, "worktree_create", task, str(path) if proc.returncode == 0 else None, branch, output=proc.stdout[-MAX_TEST_OUTPUT:]).to_json()


def _patch_paths(patch: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            rel = line[6:].strip()
            if rel == "/dev/null":
                continue
            _allowed_repo_path(rel)
            paths.append(rel)
    if not paths:
        raise ValueError("patch contains no allowed file paths")
    return tuple(dict.fromkeys(paths))


def apply_patch(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        raise FileNotFoundError("developer worktree does not exist")
    patch = str(args.get("patch") or "")
    if not patch or len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("patch missing or too large")
    paths = _patch_paths(patch)
    check = _run(["git", "apply", "--check", "-"], cwd=path, timeout=30, input_text=patch)
    if check.returncode != 0:
        return DeveloperActionResult(False, "apply_patch", task, str(path), _branch(task), "git apply --check failed", check.stdout[-MAX_TEST_OUTPUT:]).to_json()
    proc = _run(["git", "apply", "-"], cwd=path, timeout=30, input_text=patch)
    result = DeveloperActionResult(proc.returncode == 0, "apply_patch", task, str(path), _branch(task), f"paths={','.join(paths)}", proc.stdout[-MAX_TEST_OUTPUT:]).to_json()
    result["changed_paths"] = list(paths)
    return result


def run_tests(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        raise FileNotFoundError("developer worktree does not exist")
    raw_targets = str(args.get("targets") or "").strip()
    if raw_targets:
        targets = [item for item in re.split(r"[\s,]+", raw_targets) if item]
        if not targets or len(targets) > 30 or any(not _SAFE_TEST_TARGET_RE.fullmatch(item) for item in targets):
            raise ValueError("unsafe test target")
        cmd = [str(PYTHON), "-m", "unittest", "-q", *targets]
    else:
        cmd = [str(PYTHON), "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_*.py", "-q"]
    env_path = f"{path / 'src'}:{path / 'tests' / 'unit'}:{path / 'tests' / 'integration'}"
    proc = subprocess.run(cmd, cwd=str(path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300, check=False, env={**os.environ, "PYTHONPATH": env_path})
    return DeveloperActionResult(proc.returncode == 0, "run_tests", task, str(path), _branch(task), f"returncode={proc.returncode}", proc.stdout[-MAX_TEST_OUTPUT:]).to_json()


def commit_changes(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        raise FileNotFoundError("developer worktree does not exist")
    message = str(args.get("message") or "").strip()[:200]
    if len(message) < 3 or "\n" in message:
        raise ValueError("commit message must be a single bounded line")
    status = _run(["git", "status", "--porcelain"], cwd=path, timeout=15)
    changed: list[str] = []
    for line in status.stdout.splitlines():
        rel = line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        _allowed_repo_path(rel, root=path)
        changed.append(rel)
    if not changed:
        return DeveloperActionResult(False, "commit", task, str(path), _branch(task), "no changes to commit").to_json()
    add = _run(["git", "add", "--", *changed], cwd=path, timeout=30)
    if add.returncode != 0:
        return DeveloperActionResult(False, "commit", task, str(path), _branch(task), "git add failed", add.stdout[-MAX_TEST_OUTPUT:]).to_json()
    proc = _run(["git", "commit", "-m", message], cwd=path, timeout=60)
    result = DeveloperActionResult(proc.returncode == 0, "commit", task, str(path), _branch(task), output=proc.stdout[-MAX_TEST_OUTPUT:]).to_json()
    result["changed_paths"] = changed
    return result


def push_branch(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        raise FileNotFoundError("developer worktree does not exist")
    branch = _branch(task)
    proc = _run(["git", "push", "-u", "origin", branch], cwd=path, timeout=120)
    return DeveloperActionResult(proc.returncode == 0, "push", task, str(path), branch, output=proc.stdout[-MAX_TEST_OUTPUT:]).to_json()


def create_pr(args: dict[str, object]) -> dict[str, object]:
    task = _task_id(args.get("task_id"))
    path = _worktree(task)
    if not path.is_dir():
        raise FileNotFoundError("developer worktree does not exist")
    title = str(args.get("title") or "").strip()[:160]
    body = str(args.get("body") or "").strip()[:6000]
    if len(title) < 3:
        raise ValueError("PR title required")
    branch = _branch(task)
    proc = _run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body or "Gaon developer-agent generated change for human review."], cwd=path, timeout=120)
    return DeveloperActionResult(proc.returncode == 0, "create_pr", task, str(path), branch, output=proc.stdout[-MAX_TEST_OUTPUT:]).to_json()


WRITE_ACTIONS = {
    "worktree_create": worktree_create,
    "apply_patch": apply_patch,
    "run_tests": run_tests,
    "commit": commit_changes,
    "push": push_branch,
    "create_pr": create_pr,
}
