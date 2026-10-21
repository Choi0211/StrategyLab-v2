"""One-time administrator passkey login assertion; no session issued here."""
from __future__ import annotations
import json
from gaon.control.passkey_origin import RP_ID,validate_origin
from gaon.control.passkey_repository import credential_for_actor,accept_verified_assertion
from gaon.control.passkey_assertion import begin_assertion,finish_assertion,client_challenge
from gaon.control.passkey_challenge_store import store,consume

def begin_login(connection,*,actor,origin,request_host,now=None):
    validate_origin(origin,request_host=request_host)
    if not isinstance(actor,str) or not actor:
        raise PermissionError("invalid administrator")
    row=credential_for_actor(connection,actor)
    if row is None:
        raise PermissionError("unknown administrator")
    options,pending=begin_assertion(rp_id=RP_ID,credential_id=row[0],
        actor=actor,action="login",family_id="admin",version_id="session",now=now)
    store(connection,pending)
    return json.loads(options)

def finish_login(connection,*,actor,credential,origin,request_host,now=None):
    validate_origin(origin,request_host=request_host)
    if not isinstance(actor,str) or not isinstance(credential,dict):
        raise PermissionError("invalid login")
    challenge=client_challenge(credential)
    pending=consume(connection,challenge=challenge,actor=actor,action="login",
        family_id="admin",version_id="session",now=now)
    row=credential_for_actor(connection,actor)
    if row is None:
        raise PermissionError("unknown administrator")
    verified=finish_assertion(pending=pending,credential=credential,
        credential_public_key=row[1],sign_count=row[2],rp_id=RP_ID,
        origin=origin,actor=actor,action="login",family_id="admin",
        version_id="session",now=now)
    accept_verified_assertion(connection,actor=actor,verified=verified,
        expected_credential_id=row[0])
    return {"authenticated":True}
