"""Read-only MyMoneyGuard (Korean + US stock) adapter.

MyMoneyGuard (/root/MyMoneyGuard/) is a SEPARATE, already-live, real-money
trading system (KIS - Korea Investment & Securities - for both KR and US
stocks) with its own cron jobs, its own Telegram-based control plane, and
no relationship to Gaon or Passkey today. This adapter does NOT change
that: it never reads MyMoneyGuard's own files directly (this process's
user has no filesystem access into /root/MyMoneyGuard - that directory is
mode 700, root-only), never calls the KIS API, and never writes anything
anywhere.

What it reads is a single, already-sanitized snapshot file that
binance-trading's own `mymoneyguard_readonly_export.py` writes
periodically (as a separate, new, read-only root cron/systemd job - never
MyMoneyGuard's own automation) after stripping every secret (KIS_APP_KEY/
SECRET/CANO, Telegram token, KIS token) from MyMoneyGuard's local JSON
state files. This module just parses that one file; if it is missing or
stale, `read()` says so honestly rather than fabricating a status.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

DEFAULT_SNAPSHOT_PATH = "/opt/binance-trading/mymoneyguard_snapshot.json"
# Past this age, the snapshot is treated as stale rather than displayed as
# current - the exporter is expected to refresh it every ~10 minutes.
STALE_AFTER_SECONDS = 30 * 60


@dataclass(frozen=True)
class MyMoneyGuardSnapshotReader:
    # Resolved against the module global (and env var) at READ time, not
    # bound once at dataclass-field-default-evaluation time - the same
    # "default argument bound at def time" pitfall fixed in
    # gaon_hypothesis_backtest.py's _load_state/_save_state, and for the
    # same reason: a test (or future caller) that patches this module's
    # DEFAULT_SNAPSHOT_PATH or the env var must actually take effect.
    path: str | None = None

    def _resolved_path(self) -> str:
        if self.path is not None:
            return self.path
        return os.getenv("MYMONEYGUARD_SNAPSHOT_PATH", DEFAULT_SNAPSHOT_PATH)

    def read(self, *, now: datetime | None = None) -> Mapping[str, object]:
        now = now or datetime.now(timezone.utc)
        p = Path(self._resolved_path())
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            return {"available": False, "reason": "snapshot_not_found", "markets": {}}
        try:
            data = json.loads(raw)
        except ValueError:
            return {"available": False, "reason": "snapshot_unreadable", "markets": {}}
        if not isinstance(data, dict):
            return {"available": False, "reason": "snapshot_invalid_format", "markets": {}}

        generated_at = data.get("generated_at_utc")
        age_seconds = None
        if isinstance(generated_at, str):
            try:
                parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age_seconds = round((now - parsed.astimezone(timezone.utc)).total_seconds(), 1)
            except ValueError:
                age_seconds = None
        stale = age_seconds is None or age_seconds > STALE_AFTER_SECONDS

        return {
            "available": True,
            "stale": stale,
            "age_seconds": age_seconds,
            "generated_at_utc": generated_at,
            "markets": data.get("markets") or {},
            "read_only": True,
            "order_execution_connected": False,
            "source_note": "sanitized periodic export of local MyMoneyGuard state files - no live KIS calls, no secrets",
        }
