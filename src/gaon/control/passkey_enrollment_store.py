"""Persist WebAuthn enrollment challenge after consuming local bootstrap grant."""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone
from gaon.control.passkey_enrollment import PendingEnrollment,begin_enrollment
from gaon.control.passkey_bootstrap import consume_local_grant
from gaon.control.passkey_origin import RP_ID,validate_origin

def initialize(connection:sqlite3.Connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_passkey_enrollments(
      challenge BLOB PRIMARY KEY, actor TEXT NOT NULL, expires_at TEXT NOT NULL,
      consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)))""")
    connection.commit()

def begin_trusted_enrollment(connection,*,actor,token,origin,request_host,now=None):
    validate_origin(origin,request_host=request_host)
    consume_local_grant(connection,actor=actor,token=token,now=now)
    options,pending=begin_enrollment(rp_id=RP_ID,actor=actor,
        bootstrap_authorized=True,now=now)
    initialize(connection)
    with connection:
        connection.execute("INSERT INTO gaon_passkey_enrollments VALUES(?,?,?,0)",
          (pending.challenge,pending.actor,pending.expires_at.isoformat()))
    return options

def consume_enrollment(connection,*,challenge,actor,now=None):
    current=now or datetime.now(timezone.utc)
    initialize(connection)
    with connection:
        row=connection.execute("""SELECT expires_at FROM gaon_passkey_enrollments
          WHERE challenge=? AND actor=? AND consumed=0""",
          (challenge,actor)).fetchone()
        if row is None or current>datetime.fromisoformat(row[0]):
            raise PermissionError("enrollment invalid or expired")
        changed=connection.execute("""UPDATE gaon_passkey_enrollments
          SET consumed=1 WHERE challenge=? AND actor=? AND consumed=0""",
          (challenge,actor)).rowcount
        if changed!=1:
            raise PermissionError("enrollment replay")
    return PendingEnrollment(challenge,actor,datetime.fromisoformat(row[0]))
