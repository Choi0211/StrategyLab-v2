"""Durable one-time WebAuthn challenge storage for concurrent web workers."""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone
from gaon.control.passkey_assertion import PendingChallenge

def initialize(connection:sqlite3.Connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_passkey_challenges(
        challenge BLOB PRIMARY KEY, actor TEXT NOT NULL,
        action TEXT NOT NULL, family_id TEXT NOT NULL,
        version_id TEXT NOT NULL, expires_at TEXT NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)))""")
    connection.commit()

def store(connection:sqlite3.Connection,pending:PendingChallenge):
    initialize(connection)
    with connection:
        connection.execute("""INSERT INTO gaon_passkey_challenges
          (challenge,actor,action,family_id,version_id,expires_at)
          VALUES(?,?,?,?,?,?)""",(pending.challenge,pending.actor,
            pending.action,pending.family_id,pending.version_id,
            pending.expires_at.isoformat()))

def consume(connection:sqlite3.Connection,*,challenge:bytes,actor:str,action:str,
            family_id:str,version_id:str,now=None)->PendingChallenge:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise PermissionError("timezone required")
    initialize(connection)
    with connection:
        row=connection.execute("""SELECT expires_at FROM gaon_passkey_challenges
          WHERE challenge=? AND actor=? AND action=? AND family_id=?
          AND version_id=? AND consumed=0""",
          (challenge,actor,action,family_id,version_id)).fetchone()
        if row is None:
            raise PermissionError("challenge not found or already consumed")
        expiry=datetime.fromisoformat(row[0])
        if current>expiry:
            raise PermissionError("challenge expired")
        changed=connection.execute("""UPDATE gaon_passkey_challenges
          SET consumed=1 WHERE challenge=? AND consumed=0""",(challenge,)).rowcount
        if changed!=1:
            raise PermissionError("challenge replay")
    return PendingChallenge(challenge,actor,action,family_id,version_id,expiry)
