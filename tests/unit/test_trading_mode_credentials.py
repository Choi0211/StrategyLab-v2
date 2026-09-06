"""Priority 1 / C3 - CredentialProfile + provider interface + redaction.

The controller never stores an API key/secret - only a profile
identifier (DEMO / LIVE). A CredentialProvider resolves a profile to
real credentials from a protected source; tests use only
FakeCredentialProvider. The BrokerCredentials value never leaks its
secret through repr / str / logs / exception messages.
"""

from __future__ import annotations

import logging
import unittest

from gaon.control.credentials import (
    BrokerCredentials,
    CredentialProfile,
    FakeCredentialProvider,
    UnknownCredentialProfileError,
    redact_secrets,
)

_KEY = "AKIA-DEMO-KEY-1234567890"
_SECRET = "s3cr3t-demo-abcdefghijklmnopqrstuvwxyz"


class CredentialProfileTests(unittest.TestCase):
    def test_only_demo_and_live_identifiers(self) -> None:
        self.assertEqual({p.value for p in CredentialProfile}, {"demo", "live"})


class BrokerCredentialsRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.creds = BrokerCredentials(CredentialProfile.DEMO, _KEY, _SECRET)

    def test_repr_hides_key_and_secret(self) -> None:
        text = repr(self.creds)
        self.assertNotIn(_KEY, text)
        self.assertNotIn(_SECRET, text)
        self.assertIn("demo", text)
        self.assertIn("REDACTED", text)

    def test_str_hides_key_and_secret(self) -> None:
        text = str(self.creds)
        self.assertNotIn(_KEY, text)
        self.assertNotIn(_SECRET, text)

    def test_the_real_values_are_still_accessible_via_named_attributes(self) -> None:
        self.assertEqual(self.creds.api_key, _KEY)
        self.assertEqual(self.creds.api_secret, _SECRET)

    def test_redact_secrets_scrubs_arbitrary_text(self) -> None:
        line = f"connecting with key={_KEY} secret={_SECRET} to demo endpoint"
        cleaned = redact_secrets(line, self.creds)
        self.assertNotIn(_KEY, cleaned)
        self.assertNotIn(_SECRET, cleaned)
        self.assertIn("demo endpoint", cleaned)

    def test_redact_secrets_is_a_noop_when_nothing_matches(self) -> None:
        self.assertEqual(redact_secrets("no secrets here", self.creds), "no secrets here")

    def test_log_record_formatted_through_redaction_filter_is_clean(self) -> None:
        from gaon.control.credentials import SecretRedactingFilter

        logger = logging.getLogger("test.gaon.control.credentials")
        logger.setLevel(logging.INFO)
        records: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        handler = _Capture()
        handler.addFilter(SecretRedactingFilter(self.creds))
        logger.addHandler(handler)
        self.addCleanup(lambda: logger.removeHandler(handler))
        logger.info("auth failed for key=%s secret=%s", _KEY, _SECRET)
        self.assertTrue(records)
        self.assertNotIn(_KEY, records[0])
        self.assertNotIn(_SECRET, records[0])


class FakeCredentialProviderTests(unittest.TestCase):
    def test_loads_the_requested_profile(self) -> None:
        provider = FakeCredentialProvider({CredentialProfile.DEMO: (_KEY, _SECRET)})
        creds = provider.load(CredentialProfile.DEMO)
        self.assertIs(creds.profile, CredentialProfile.DEMO)
        self.assertEqual(creds.api_key, _KEY)

    def test_unknown_profile_raises_a_domain_error_without_leaking_any_secret(self) -> None:
        provider = FakeCredentialProvider({CredentialProfile.DEMO: (_KEY, _SECRET)})
        with self.assertRaises(UnknownCredentialProfileError) as ctx:
            provider.load(CredentialProfile.LIVE)
        message = str(ctx.exception)
        self.assertNotIn(_KEY, message)
        self.assertNotIn(_SECRET, message)
        self.assertIn("live", message)

    def test_provider_error_message_never_echoes_a_configured_secret(self) -> None:
        # even the DEMO secret it *does* hold must not appear in an error.
        provider = FakeCredentialProvider({CredentialProfile.DEMO: (_KEY, _SECRET)})
        try:
            provider.load(CredentialProfile.LIVE)
        except UnknownCredentialProfileError as exc:
            self.assertNotIn(_SECRET, repr(exc))
            self.assertNotIn(_KEY, repr(exc))


if __name__ == "__main__":
    unittest.main()
