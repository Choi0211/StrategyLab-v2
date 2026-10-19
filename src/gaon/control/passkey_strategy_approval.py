"""Verified passkey assertion -> scoped strategy activation.

Only the successful WebAuthn signature verification result can reach the
mutation transaction. Caller-supplied 'approved' flags are not accepted.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from gaon.control.passkey_assertion import finish_assertion
from gaon.control.passkey_repository import credential_for_actor,accept_verified_assertion
from gaon.control.trusted_strategy_activation import activate_approved_version

def approve_with_passkey(connection, *, pending, credential, actor, action,
                         family_id, strategy_version_id, rp_id, origin, now=None):
    if action not in ("activate","rollback"):
        raise PermissionError("strategy action required")
    row=credential_for_actor(connection,actor)
    if row is None:
        raise PermissionError("registered administrator passkey required")
    credential_id,public_key,sign_count=row
    current=now or datetime.now(timezone.utc)
    verified=finish_assertion(
        pending=pending,credential=credential,
        credential_public_key=public_key,sign_count=sign_count,
        rp_id=rp_id,origin=origin,actor=actor,action=action,
        family_id=family_id,version_id=strategy_version_id,now=current)
    if verified.credential_id!=credential_id:
        raise PermissionError("passkey credential mismatch")
    accept_verified_assertion(connection,actor=actor,verified=verified,
                              expected_credential_id=credential_id)
    stamp=current.isoformat()
    return activate_approved_version(
        connection,family_id=family_id,strategy_version_id=strategy_version_id,
        authenticated_actor=actor,approval_id=str(uuid4()),
        approved_family_id=family_id,approved_strategy_version_id=strategy_version_id,
        approval_actor=actor,approved_at=stamp,
        expires_at=(current+timedelta(seconds=30)).isoformat(),now=stamp)
