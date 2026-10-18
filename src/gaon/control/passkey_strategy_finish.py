"""Complete a durable one-time WebAuthn strategy approval.

HTTP integration must enforce Origin/Host, CSRF, and request rate limits.
No browser-supplied approval status or identity is trusted.
"""
from __future__ import annotations
from gaon.control.passkey_origin import RP_ID,validate_origin
from gaon.control.passkey_challenge_store import consume
from gaon.control.passkey_strategy_approval import approve_with_passkey

def finish_strategy_approval(connection,*,challenge:bytes,credential:dict,
                             actor:str,action:str,family_id:str,version_id:str,
                             origin:str,request_host:str,now=None):
    validated_origin=validate_origin(origin,request_host=request_host)
    if action not in ("activate","rollback"):
        raise PermissionError("invalid strategy action")
    if not isinstance(credential,dict):
        raise PermissionError("invalid passkey assertion")
    pending=consume(connection,challenge=challenge,actor=actor,action=action,
                    family_id=family_id,version_id=version_id,now=now)
    return approve_with_passkey(connection,pending=pending,credential=credential,
        actor=actor,action=action,family_id=family_id,
        strategy_version_id=version_id,rp_id=RP_ID,origin=validated_origin,now=now)
