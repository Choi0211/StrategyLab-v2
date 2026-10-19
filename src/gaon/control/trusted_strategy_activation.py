"""Offline-only strategy activation transaction with externally authenticated actor.

This is NOT an HTTP authentication mechanism. Only a trusted caller that has
already authenticated the human may call this service. No orders are placed.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository

def activate_approved_version(connection:sqlite3.Connection, *, family_id:str,
    strategy_version_id:str, authenticated_actor:str, approval_id:str,
    approved_family_id:str, approved_strategy_version_id:str,
    approval_actor:str, approved_at:str, expires_at:str, now:str):
    if not all(isinstance(x,str) and x.strip() for x in (
        family_id,strategy_version_id,authenticated_actor,approval_id,
        approved_family_id,approved_strategy_version_id,approval_actor)):
        raise PermissionError("trusted identity and exact-version approval required")
    if (family_id!=approved_family_id or strategy_version_id!=approved_strategy_version_id
        or authenticated_actor!=approval_actor):
        raise PermissionError("approval scope mismatch")
    def timestamp(s):
        d=datetime.fromisoformat(s.replace("Z","+00:00"))
        if d.tzinfo is None:raise PermissionError("timezone required")
        return d.astimezone(timezone.utc)
    if not timestamp(approved_at)<=timestamp(now)<=timestamp(expires_at):
        raise PermissionError("approval expired or future dated")
    # Single transaction for token consumption, immutable audit and registry.
    # Never invoke repository.save here: it commits independently.
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS gaon_strategy_activation_audit(
          approval_id TEXT PRIMARY KEY, actor TEXT NOT NULL, family_id TEXT NOT NULL,
          strategy_version_id TEXT NOT NULL, approved_at TEXT NOT NULL,
          activated_at TEXT NOT NULL)""")
        if connection.execute("SELECT 1 FROM gaon_strategy_activation_audit WHERE approval_id=?",
                              (approval_id,)).fetchone():
            raise PermissionError("approval already consumed")
        repo=StrategyVersionSQLiteRepository(connection)
        registry=repo.get(family_id)
        version=registry.get(strategy_version_id)
        if version.family_id!=family_id or version.status.value not in ("apply_ready","previous"):
            raise PermissionError("version not eligible")
        registry.mark_active(strategy_version_id,at=now)
        from gaon.runtime.serialization import dumps_json
        connection.execute("""INSERT INTO strategy_version_registries(family_id,registry_json,updated_at)
          VALUES(?,?,?) ON CONFLICT(family_id) DO UPDATE SET
          registry_json=excluded.registry_json,updated_at=excluded.updated_at""",
          (family_id,dumps_json(registry.to_json()),now))
        connection.execute("INSERT INTO gaon_strategy_activation_audit VALUES(?,?,?,?,?,?)",
          (approval_id,authenticated_actor,family_id,strategy_version_id,approved_at,now))
        connection.commit()
        return {"activated":strategy_version_id,"actor":authenticated_actor,
                "approval_consumed":True,"orders_executed":False}
    except BaseException:
        connection.rollback()
        raise
