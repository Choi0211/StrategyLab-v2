"""Finish enrollment using verified WebAuthn registration, never browser claims."""
from __future__ import annotations
from gaon.control.passkey_assertion import client_challenge
from gaon.control.passkey_enrollment import finish_enrollment
from gaon.control.passkey_enrollment_store import consume_enrollment
from gaon.control.passkey_origin import RP_ID,validate_origin
from gaon.control.passkey_repository import enroll_verified

def finish_trusted_enrollment(connection,*,actor,credential,origin,request_host,now=None):
    validated_origin=validate_origin(origin,request_host=request_host)
    if not isinstance(actor,str) or not actor or not isinstance(credential,dict):
        raise PermissionError("invalid enrollment request")
    challenge=client_challenge(credential)
    pending=consume_enrollment(connection,challenge=challenge,actor=actor,now=now)
    verified=finish_enrollment(pending=pending,credential=credential,
        rp_id=RP_ID,origin=validated_origin,actor=actor,now=now)
    enroll_verified(connection,actor=actor,verified=verified,trusted_bootstrap=True)
    return {"registered":True}
