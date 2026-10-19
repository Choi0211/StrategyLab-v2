"""Persistent, one-time, local-operator bootstrap grants for passkey enrollment.

Token hashes only; do not expose grant creation over HTTP. The local operator
must communicate the token out-of-band to the actual administrator.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime,timedelta,timezone

def initialize(connection:sqlite3.Connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_passkey_bootstrap(
      token_hash BLOB PRIMARY KEY, actor TEXT NOT NULL,
      expires_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
      CHECK(consumed IN (0,1)))""")
    connection.commit()

def create_local_grant(connection:sqlite3.Connection,*,actor:str,now=None):
    if not actor or len(actor)>128:
        raise ValueError("invalid actor")
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timezone required")
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode()).digest()
    initialize(connection)
    with connection:
        connection.execute("INSERT INTO gaon_passkey_bootstrap VALUES(?,?,?,0)",
          (digest,actor,(current+timedelta(minutes=10)).isoformat()))
    return token

def consume_local_grant(connection:sqlite3.Connection,*,actor:str,token:str,now=None):
    if not isinstance(token,str) or len(token)>256:
        raise PermissionError("invalid grant")
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise PermissionError("timezone required")
    digest=hashlib.sha256(token.encode()).digest()
    initialize(connection)
    with connection:
        row=connection.execute("""SELECT expires_at FROM gaon_passkey_bootstrap
          WHERE token_hash=? AND actor=? AND consumed=0""",(digest,actor)).fetchone()
        if row is None or current>datetime.fromisoformat(row[0]):
            raise PermissionError("grant invalid or expired")
        updated=connection.execute("""UPDATE gaon_passkey_bootstrap
          SET consumed=1 WHERE token_hash=? AND actor=? AND consumed=0""",
          (digest,actor)).rowcount
        if updated!=1:
            raise PermissionError("grant already used")
    return True
