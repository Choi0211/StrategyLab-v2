"""Server-side administrator session issued only after verified WebAuthn login."""
from __future__ import annotations
import hashlib,hmac,secrets,sqlite3
from datetime import datetime,timezone,timedelta

def initialize(connection:sqlite3.Connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_admin_sessions(
      token_hash BLOB PRIMARY KEY, actor TEXT NOT NULL, csrf_hash BLOB NOT NULL,
      expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
      CHECK(revoked IN (0,1)))""")
    connection.commit()

def create_session(connection,*,actor,authenticated=False,now=None):
    if authenticated is not True or not isinstance(actor,str) or not actor:
        raise PermissionError("verified passkey login required")
    current=now or datetime.now(timezone.utc)
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(32)
    initialize(connection)
    with connection:
        connection.execute("""INSERT INTO gaon_admin_sessions
          (token_hash,actor,csrf_hash,expires_at) VALUES(?,?,?,?)""",
          (hashlib.sha256(token.encode()).digest(),actor,
           hashlib.sha256(csrf.encode()).digest(),
           (current+timedelta(minutes=20)).isoformat()))
    return token,csrf

def validate_session(connection,*,token,csrf=None,require_csrf=False,now=None):
    if not isinstance(token,str) or not token:
        raise PermissionError("missing session")
    if require_csrf and (not isinstance(csrf,str) or not csrf):
        raise PermissionError("missing csrf")
    initialize(connection)
    row=connection.execute("""SELECT actor,csrf_hash,expires_at FROM gaon_admin_sessions
       WHERE token_hash=? AND revoked=0""",
       (hashlib.sha256(token.encode()).digest(),)).fetchone()
    current=now or datetime.now(timezone.utc)
    if row is None or current>datetime.fromisoformat(row[2]):
        raise PermissionError("session invalid or expired")
    if require_csrf and not hmac.compare_digest(
       row[1],hashlib.sha256(csrf.encode()).digest()):
        raise PermissionError("invalid csrf")
    return row[0]

def revoke_session(connection,*,token):
    initialize(connection)
    with connection:
        connection.execute("UPDATE gaon_admin_sessions SET revoked=1 WHERE token_hash=?",
            (hashlib.sha256(token.encode()).digest(),))
