"""Strict origin validation for Gaon WebAuthn admin requests."""
from __future__ import annotations
from urllib.parse import urlsplit

RP_ID="mymoneyguard.tail56fef5.ts.net"
ALLOWED_ORIGINS=frozenset({
    "https://mymoneyguard.tail56fef5.ts.net",
    "https://mymoneyguard.tail56fef5.ts.net:8443",
})

def validate_origin(origin:str,*,request_host:str,expected_origin:str|None=None)->str:
    if not isinstance(origin,str) or origin not in ALLOWED_ORIGINS:
        raise PermissionError("untrusted WebAuthn origin")
    parsed=urlsplit(origin)
    if parsed.scheme!="https" or parsed.hostname!=RP_ID:
        raise PermissionError("invalid WebAuthn origin")
    if parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise PermissionError("invalid WebAuthn origin")
    if request_host not in (RP_ID,RP_ID+":8443"):
        raise PermissionError("untrusted request host")
    if parsed.netloc!=request_host:
        raise PermissionError("cross-origin admin request")
    if expected_origin is not None and origin!=expected_origin:
        raise PermissionError("origin mismatch")
    return origin
