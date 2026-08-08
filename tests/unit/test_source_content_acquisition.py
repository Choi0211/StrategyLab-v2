from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from gaon.knowledge.content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionPolicy,
    ContentAcquisitionStatus,
    ContentAcquisitionTarget,
    ContentFailureKind,
    FixtureBinaryTransport,
    canonical_acquisition_id,
    content_acquisition_release_check,
    validate_content_url,
)
from gaon.knowledge.discovery import (
    DiscoveryProvider,
    DiscoveryResult,
    DiscoveryStatus,
)
from gaon.knowledge.provenance import (
    SourceType,
)
from gaon.storage.foundation import (
    GaonStorage,
)


def discovery_result() -> DiscoveryResult:
    return DiscoveryResult(
        result_id="discovery-result:test",
        query_id="discovery-query:test",
        provider=(
            DiscoveryProvider.ACADEMIC_SEARCH
        ),
        title="Research Paper",
        locator=(
            "https://doi.org/10.1000/test"
        ),
        source_type=
            SourceType.ACADEMIC_PAPER,
        status=DiscoveryStatus.DISCOVERED,
    )


def target() -> ContentAcquisitionTarget:
    return (
        ContentAcquisitionTarget.from_discovery(
            discovery_result(),
            content_url=(
                "https://content.example.org/"
                "paper.txt"
            ),
        )
    )


def enabled_policy() -> ContentAcquisitionPolicy:
    return ContentAcquisitionPolicy(
        network_enabled=True,
        allowed_hosts=(
            "content.example.org",
        ),
        max_content_bytes=1024,
    )


class SourceContentAcquisitionTests(
    unittest.TestCase
):
    def test_acquisition_id_is_deterministic(
        self,
    ) -> None:
        self.assertEqual(
            canonical_acquisition_id(
                target()
            ),
            canonical_acquisition_id(
                target()
            ),
        )

    def test_network_disabled_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=(
                        ContentAcquisitionPolicy(
                            network_enabled=False,
                            allowed_hosts=(
                                "content.example.org",
                            ),
                        )
                    ),
                    transport=(
                        FixtureBinaryTransport()
                    ),
                ).acquire(target())
            )

            self.assertEqual(
                record.status,
                ContentAcquisitionStatus.BLOCKED,
            )

            self.assertEqual(
                record.failure_kind,
                ContentFailureKind.NETWORK_DISABLED,
            )

    def test_fixture_content_is_acquired_and_stored(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=(
                        FixtureBinaryTransport()
                    ),
                ).acquire(target())
            )

            self.assertEqual(
                record.status,
                ContentAcquisitionStatus.ACQUIRED,
            )

            self.assertTrue(
                record.actual_source_body_fetched
            )

            self.assertTrue(
                record.stored_as_inert_evidence
            )

            self.assertTrue(
                Path(
                    record.raw_path
                ).is_file()
            )

    def test_claim_extraction_is_not_started(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=FixtureBinaryTransport(),
                ).acquire(target())
            )

            self.assertFalse(
                record.eligible_for_claim_extraction
            )

            self.assertFalse(
                record.knowledge_validated
            )

    def test_non_https_url_is_blocked(
        self,
    ) -> None:
        bad = replace(
            target(),
            content_url=(
                "http://content.example.org/"
                "paper.txt"
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=FixtureBinaryTransport(),
                ).acquire(bad)
            )

            self.assertEqual(
                record.status,
                ContentAcquisitionStatus.BLOCKED,
            )

    def test_non_allowlisted_host_is_blocked(
        self,
    ) -> None:
        bad = replace(
            target(),
            content_url=(
                "https://evil.example/"
                "paper.txt"
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=FixtureBinaryTransport(),
                ).acquire(bad)
            )

            self.assertEqual(
                record.failure_kind,
                ContentFailureKind.HOST_NOT_ALLOWED,
            )

    def test_private_literal_ip_is_blocked(
        self,
    ) -> None:
        policy = (
            ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("127.0.0.1",),
            )
        )

        with self.assertRaises(
            PermissionError
        ):
            validate_content_url(
                "https://127.0.0.1/test",
                policy=policy,
                resolve_dns=False,
            )

    def test_blocked_mime_is_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=FixtureBinaryTransport(
                        content_type=(
                            "application/octet-stream"
                        ),
                    ),
                ).acquire(target())
            )

            self.assertEqual(
                record.failure_kind,
                ContentFailureKind.MIME_BLOCKED,
            )

    def test_size_budget_is_enforced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = (
                ContentAcquisitionPolicy(
                    network_enabled=True,
                    allowed_hosts=(
                        "content.example.org",
                    ),
                    max_content_bytes=5,
                )
            )

            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=policy,
                    transport=FixtureBinaryTransport(
                        content=b"123456",
                    ),
                ).acquire(target())
            )

            self.assertEqual(
                record.failure_kind,
                ContentFailureKind.SIZE_EXCEEDED,
            )

    def test_non_discovered_result_cannot_be_target(
        self,
    ) -> None:
        blocked = replace(
            discovery_result(),
            status=DiscoveryStatus.BLOCKED,
        )

        with self.assertRaises(
            ValueError
        ):
            ContentAcquisitionTarget.from_discovery(
                blocked,
                content_url=(
                    "https://content.example.org/"
                    "paper.txt"
                ),
            )

    def test_acquired_content_never_mutates_or_orders(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                BoundedSourceContentAcquirer(
                    GaonStorage(tmp),
                    policy=enabled_policy(),
                    transport=FixtureBinaryTransport(),
                ).acquire(target())
            )

            self.assertFalse(
                record.production_approved
            )

            self.assertFalse(
                record.strategy_mutated
            )

            self.assertFalse(
                record.order_executed
            )

    def test_release_check(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = (
                content_acquisition_release_check(
                    tmp
                )
            )

            self.assertEqual(
                payload["safety"],
                "pass",
            )


if __name__ == "__main__":
    unittest.main()
