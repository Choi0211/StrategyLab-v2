"""Priority 1 / C3 - credential PROFILES, never credential VALUES.

The Trading Mode Controller stores only a profile identifier
(``CredentialProfile.DEMO`` / ``.LIVE``). Resolving a profile to a real
API key/secret is the job of a ``CredentialProvider`` backed by a
protected source (env / secrets manager) - never persisted by the
controller, never logged, never put in an exception message.

``BrokerCredentials`` carries the real values for the code that actually
opens a broker session, but redacts them from ``repr`` / ``str``;
``redact_secrets`` scrubs them from arbitrary text; ``SecretRedacting
Filter`` scrubs them from log records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Protocol

_REDACTED = "***REDACTED***"


class CredentialProfile(str, Enum):
    DEMO = "demo"
    LIVE = "live"


class UnknownCredentialProfileError(LookupError):
    """A profile was requested that the provider has no credentials for.
    Its message names only the profile - never any configured key/secret."""


@dataclass(frozen=True)
class BrokerCredentials:
    """The resolved key/secret for one profile. Real values are reachable
    ONLY via the named attributes ``api_key`` / ``api_secret`` - every
    string rendering (repr, str, f-string) is redacted."""

    profile: CredentialProfile
    api_key: str
    api_secret: str

    def __repr__(self) -> str:  # noqa: D401 - deliberately redacted
        return f"BrokerCredentials(profile={self.profile.value!r}, api_key={_REDACTED}, api_secret={_REDACTED})"

    __str__ = __repr__

    def _secret_values(self) -> tuple[str, ...]:
        return tuple(v for v in (self.api_key, self.api_secret) if v)


def redact_secrets(text: str, *sources: "BrokerCredentials | Iterable[str]") -> str:
    """Replace every configured key/secret substring in ``text`` with a
    redaction marker. ``sources`` may be ``BrokerCredentials`` instances
    or bare iterables of secret strings. A no-op when nothing matches."""
    secrets: list[str] = []
    for source in sources:
        if isinstance(source, BrokerCredentials):
            secrets.extend(source._secret_values())
        else:
            secrets.extend(s for s in source if s)
    cleaned = text
    # longest first, so a secret that contains another is handled correctly.
    for secret in sorted(set(secrets), key=len, reverse=True):
        cleaned = cleaned.replace(secret, _REDACTED)
    return cleaned


class SecretRedactingFilter:
    """A ``logging.Filter``-compatible object: rewrites a record's
    formatted message (and args) so no configured secret is emitted."""

    def __init__(self, *sources: "BrokerCredentials | Iterable[str]") -> None:
        self._sources = sources

    def filter(self, record) -> bool:  # logging.LogRecord
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let redaction break logging
            return True
        record.msg = redact_secrets(message, *self._sources)
        record.args = None
        return True


class CredentialProvider(Protocol):
    """Resolves a profile to real credentials from a protected source."""

    def load(self, profile: CredentialProfile) -> BrokerCredentials: ...


class FakeCredentialProvider:
    """Test-only provider. Construct with a mapping of profile -> (key,
    secret); ``load`` for an absent profile raises
    ``UnknownCredentialProfileError`` whose message names only the
    profile."""

    def __init__(self, credentials: Mapping[CredentialProfile, tuple[str, str]]) -> None:
        self._credentials = dict(credentials)

    def load(self, profile: CredentialProfile) -> BrokerCredentials:
        try:
            key, secret = self._credentials[profile]
        except KeyError:
            raise UnknownCredentialProfileError(
                f"no credentials configured for profile '{profile.value}'"
            ) from None
        return BrokerCredentials(profile, key, secret)
