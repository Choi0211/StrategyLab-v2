"""Persistent passkey credential registry. No secret key or biometric stored."""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone

def initialize(connection:sqlite3.Connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_admin_passkeys(
      credential_id BLOB PRIMARY KEY, actor TEXT NOT NULL,
      public_key BLOB NOT NULL, sign_count INTEGER NOT NULL CHECK(sign_count>=0),
      created_at TEXT NOT NULL, last_used_at TEXT)""")
    connection.commit()

def enroll_verified(connection:sqlite3.Connection, *, actor:str, verified,
                    trusted_bootstrap:bool=False):
    if not trusted_bootstrap or not actor or not verified.user_verified:
        raise PermissionError("trusted bootstrap and user verification required")
    initialize(connection)
    with connection:
        connection.execute("""INSERT INTO gaon_admin_passkeys
          (credential_id,actor,public_key,sign_count,created_at)
          VALUES(?,?,?,?,?)""",(verified.credential_id,actor,
            verified.credential_public_key,verified.sign_count,
            datetime.now(timezone.utc).isoformat()))

def credential_for_actor(connection:sqlite3.Connection,actor:str):
    initialize(connection)
    return connection.execute("""SELECT credential_id,public_key,sign_count
      FROM gaon_admin_passkeys WHERE actor=? ORDER BY created_at DESC LIMIT 1""",
      (actor,)).fetchone()

def accept_verified_assertion(connection:sqlite3.Connection, *, actor:str,
                              verified, expected_credential_id:bytes):
    if not verified.user_verified or verified.credential_id!=expected_credential_id:
        raise PermissionError("passkey credential mismatch")
    initialize(connection)
    with connection:
        row=connection.execute("""SELECT sign_count FROM gaon_admin_passkeys
          WHERE credential_id=? AND actor=?""",(expected_credential_id,actor)).fetchone()
        if row is None:
            raise PermissionError("passkey not registered")
        previous=int(row[0])
        current=int(verified.new_sign_count)
        if previous and current and current<=previous:
            raise PermissionError("sign counter replay")
        connection.execute("""UPDATE gaon_admin_passkeys
          SET sign_count=?,last_used_at=? WHERE credential_id=? AND actor=?""",
          (current,datetime.now(timezone.utc).isoformat(),expected_credential_id,actor))
