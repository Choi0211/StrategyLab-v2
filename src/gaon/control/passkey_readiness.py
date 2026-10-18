"""Read-only passkey readiness for web dashboard.

Never disclose registered credential IDs or administrator identities.
This endpoint cannot enroll, authenticate or mutate a strategy.
"""
from __future__ import annotations
from gaon.control.passkey_origin import RP_ID
from gaon.control.passkey_repository import initialize

def readiness(connection):
    initialize(connection)
    registered=bool(connection.execute(
        "SELECT 1 FROM gaon_admin_passkeys LIMIT 1").fetchone())
    return {
        "passkey_rp_id":RP_ID,
        "registration_complete":registered,
        "admin_login_enabled":False,
        "strategy_approval_enabled":False,
        "strategy_mutated":False,
        "order_executed":False,
    }
