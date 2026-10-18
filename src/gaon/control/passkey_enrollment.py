"""WebAuthn credential registration: explicit trusted bootstrap only.

No unauthenticated HTTP enrollment endpoint is provided. A trusted
operator must authorize enrollment outside this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import secrets
from webauthn import generate_registration_options,verify_registration_response
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import AuthenticatorSelectionCriteria,UserVerificationRequirement

@dataclass
class PendingEnrollment:
    challenge:bytes
    actor:str
    expires_at:datetime
    consumed:bool=False

def begin_enrollment(*,rp_id,actor,bootstrap_authorized=False,now=None):
    if not bootstrap_authorized:
        raise PermissionError("trusted bootstrap required")
    if not rp_id or not actor:
        raise ValueError("rp_id and actor required")
    current=now or datetime.now(timezone.utc)
    challenge=secrets.token_bytes(32)
    options=generate_registration_options(rp_id=rp_id,rp_name="Gaon",
        user_name=actor,challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED))
    return options_to_json(options),PendingEnrollment(challenge,actor,
        current+timedelta(minutes=2))

def finish_enrollment(*,pending,credential,rp_id,origin,actor,now=None):
    current=now or datetime.now(timezone.utc)
    if pending.consumed or current>pending.expires_at or current.tzinfo is None:
        raise PermissionError("enrollment expired or consumed")
    if actor!=pending.actor:
        raise PermissionError("enrollment actor mismatch")
    pending.consumed=True
    return verify_registration_response(credential=credential,
        expected_challenge=pending.challenge,expected_rp_id=rp_id,
        expected_origin=origin,require_user_verification=True)
