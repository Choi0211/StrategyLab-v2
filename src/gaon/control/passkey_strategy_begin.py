"""Trusted server-side start of strategy passkey approval.

The HTTP layer must independently enforce HTTPS Origin/Host and rate limits.
No caller-supplied passkey approval flag is accepted.
"""
from __future__ import annotations
from gaon.control.passkey_assertion import begin_assertion
from gaon.control.passkey_challenge_store import store
from gaon.control.passkey_repository import credential_for_actor
from gaon.control.passkey_origin import RP_ID,validate_origin

def begin_strategy_approval(connection, *, actor,action,family_id,version_id,
                            origin,request_host,now=None):
    validate_origin(origin,request_host=request_host)
    if action not in ("activate","rollback"):
        raise PermissionError("strategy action required")
    row=credential_for_actor(connection,actor)
    if row is None:
        raise PermissionError("administrator passkey not registered")
    credential_id,_,_=row
    options,pending=begin_assertion(
        rp_id=RP_ID,credential_id=credential_id,actor=actor,
        action=action,family_id=family_id,version_id=version_id,now=now)
    store(connection,pending)
    return options
