"""SQLite persistence for ``gaon.control.strategy_version.StrategyVersionRegistry``.

That module is deliberately an isolated, in-memory-only dataclass ("no
production wiring, no deploy" - see its own docstring). This repository is
the durability layer that makes it survive a process restart, one registry
per ``family_id``, storing the registry's own ``to_json()``/``from_json()``
round-trip verbatim in a single JSON column (see the
``strategy_version_registries`` table added by
``gaon.runtime.migrations._upgrade_v42_to_v43``).

This module only reads and writes the registry object itself - it contains
no HTTP route, no rollback/apply action, and no connection to
``gaon.adapters.binance`` or any live trading state. See
``gaon.runtime.web_api``'s ``GET /gaon/strategy/version_status`` for the
read-only HTTP surface built on top of it, and
``docs/architecture/GaonStrategyRollbackContract.md`` for the full contract
(including what a rollback ACTION requires, and what the separate Binance
dashboard repository still needs to change).
"""

from __future__ import annotations

import sqlite3

from gaon.control.strategy_version import StrategyVersionRegistry
from gaon.runtime.serialization import dumps_json, loads_json


class StrategyVersionSQLiteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, family_id: str) -> StrategyVersionRegistry:
        """Returns the persisted registry for ``family_id``, or an empty
        (no versions at all) registry if none has ever been saved - never
        raises for an unknown family, matching ``StrategyVersionRegistry``'s
        own "no versions yet" starting state."""
        row = self._connection.execute(
            "SELECT registry_json FROM strategy_version_registries WHERE family_id = ?",
            (family_id,),
        ).fetchone()
        if row is None:
            return StrategyVersionRegistry()
        return StrategyVersionRegistry.from_json(loads_json(str(row[0])))

    def save(self, family_id: str, registry: StrategyVersionRegistry, *, now: str) -> None:
        self._connection.execute(
            """
            INSERT INTO strategy_version_registries (family_id, registry_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(family_id) DO UPDATE SET registry_json = excluded.registry_json, updated_at = excluded.updated_at
            """,
            (family_id, dumps_json(registry.to_json()), now),
        )
        self._connection.commit()
