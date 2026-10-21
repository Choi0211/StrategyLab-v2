"""Regression checks for the 2026-10-21 repository audit; no live services."""
import base64
import json
import unittest
from unittest.mock import Mock, patch

from gaon.control.passkey_assertion import begin_assertion, client_challenge, finish_assertion
from gaon.control.passkey_enrollment import begin_enrollment, finish_enrollment
from gaon.runtime.web_api import dispatch_request


class DeveloperHTTPBoundaryTests(unittest.TestCase):
    def test_self_claimed_identity_cannot_issue_or_use_developer_approval(self):
        adapter = Mock()
        for path in ("/gaon/developer/approve", "/gaon/developer/execute"):
            status, payload = dispatch_request(adapter, method="POST", path=path, body={
                "user_ref": "owner", "confirm": True, "task_id": "audit",
                "action": "push", "approval_id": "forged", "approval_token": "forged",
            })
            self.assertEqual(status, 403)
            self.assertNotIn("approval_token", payload)
        self.assertEqual(adapter.mock_calls, [])


class PasskeyInvalidInputTests(unittest.TestCase):
    def test_malformed_client_data_is_a_controlled_denial(self):
        malformed = [{}, {"response": None}, {"response": []}]
        for value in ("[]", "null", "1", '{}', '{"challenge": []}', '{"challenge": "a"}'):
            encoded = base64.urlsafe_b64encode(value.encode()).decode()
            malformed.append({"response": {"clientDataJSON": encoded}})
        malformed.append({"response": {"clientDataJSON": "%%%"}})
        for credential in malformed:
            with self.subTest(credential=credential), self.assertRaises(PermissionError):
                client_challenge(credential)

    def test_challenge_parser_preserves_exact_random_bytes(self):
        challenge = bytes(range(32))
        encoded = base64.urlsafe_b64encode(challenge).decode().rstrip("=")
        data = base64.urlsafe_b64encode(json.dumps({"challenge": encoded}).encode()).decode().rstrip("=")
        self.assertEqual(client_challenge({"response": {"clientDataJSON": data}}), challenge)

    def test_bad_signature_is_denied_and_challenge_is_burned(self):
        _, pending = begin_assertion(rp_id="example.com", credential_id=b"id", actor="owner",
            action="activate", family_id="f", version_id="v")
        with self.assertRaisesRegex(PermissionError, "verification failed"):
            finish_assertion(pending=pending, credential={}, credential_public_key=b"bad", sign_count=0,
                rp_id="example.com", origin="https://example.com", actor="owner", action="activate",
                family_id="f", version_id="v")
        self.assertTrue(pending.consumed)

    def test_bad_registration_is_denied_and_challenge_is_burned(self):
        _, pending = begin_enrollment(rp_id="example.com", actor="owner", bootstrap_authorized=True)
        with self.assertRaisesRegex(PermissionError, "verification failed"):
            finish_enrollment(pending=pending, credential={}, rp_id="example.com",
                origin="https://example.com", actor="owner")
        self.assertTrue(pending.consumed)
