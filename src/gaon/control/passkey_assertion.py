"""Passkey verification boundary: no enrollment without trusted bootstrap.

The browser/API cannot create an initial administrator. Challenges are
single-use, short-lived and bound to action + exact strategy version.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import secrets
import base64
import json
from webauthn import generate_authentication_options, verify_authentication_response
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

@dataclass
class PendingChallenge:
    challenge: bytes
    actor: str
    action: str
    family_id: str
    version_id: str
    expires_at: datetime
    consumed: bool = False

def begin_assertion(*, rp_id, credential_id:bytes, actor, action, family_id, version_id,
                    now=None):
    if action not in ("activate","rollback","login") or not all(
        isinstance(x,str) and x.strip() for x in (rp_id,actor,family_id,version_id)):
        raise ValueError("invalid passkey scope")
    current=now or datetime.now(timezone.utc)
    challenge=secrets.token_bytes(32)
    options=generate_authentication_options(
        rp_id=rp_id,challenge=challenge,
        allow_credentials=[PublicKeyCredentialDescriptor(id=credential_id)],
        user_verification=UserVerificationRequirement.REQUIRED)
    return options_to_json(options), PendingChallenge(
        challenge,actor,action,family_id,version_id,current+timedelta(minutes=2))

def finish_assertion(*, pending, credential, credential_public_key, sign_count,
                     rp_id, origin, actor, action, family_id, version_id, now=None):
    current=now or datetime.now(timezone.utc)
    if pending.consumed or current>pending.expires_at or current.tzinfo is None:
        raise PermissionError("challenge expired or consumed")
    if (pending.actor,pending.action,pending.family_id,pending.version_id)!=(
        actor,action,family_id,version_id):
        raise PermissionError("passkey scope mismatch")
    # Burn challenge before cryptographic verification, even on bad signature.
    pending.consumed=True
    try:
        return verify_authentication_response(
            credential=credential,expected_challenge=pending.challenge,
            expected_rp_id=rp_id,expected_origin=origin,
            credential_public_key=credential_public_key,
            credential_current_sign_count=sign_count,require_user_verification=True)
    except WebAuthnException as exc:
        raise PermissionError("passkey assertion verification failed") from exc


def client_challenge(credential: dict) -> bytes:
    """Parse untrusted client data; this does not verify an assertion."""
    response = credential.get("response") if isinstance(credential, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("clientDataJSON"), str):
        raise PermissionError("missing client data")
    try:
        data = response["clientDataJSON"]
        if not isinstance(data, str):
            raise ValueError("invalid client data")
        raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
        parsed = json.loads(raw)
        encoded = parsed["challenge"]
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("missing challenge")
        challenge = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if len(challenge) != 32:
            raise ValueError("invalid challenge size")
        return challenge
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise PermissionError("invalid passkey client data") from exc
