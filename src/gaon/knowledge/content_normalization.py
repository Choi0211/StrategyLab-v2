"""Sprint 175 - Safe Source Content Normalization.

Acquired source bytes are untrusted evidence. This module converts supported
MIME payloads into bounded plain text without executing source instructions,
HTML, JavaScript, or downloaded content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
import argparse
import hashlib
import json
import re
from typing import Iterable, Mapping

from .content_acquisition import ContentAcquisitionRecord, ContentAcquisitionStatus


CONTENT_NORMALIZATION_SCHEMA_VERSION = 1
DEFAULT_MAX_NORMALIZED_CHARS = 200_000
DEFAULT_MAX_JSON_TEXT_VALUES = 200

_SPACE_RE = re.compile(r"\s+")


class ContentNormalizationStatus(str, Enum):
    NORMALIZED = "normalized"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class NormalizationFailureKind(str, Enum):
    ACQUISITION_NOT_ELIGIBLE = "acquisition_not_eligible"
    MIME_UNSUPPORTED = "mime_unsupported"
    INVALID_JSON = "invalid_json"
    PDF_TEXT_UNAVAILABLE = "pdf_text_unavailable"
    EMPTY_TEXT = "empty_text"
    SIZE_EXCEEDED = "size_exceeded"


@dataclass(frozen=True)
class NormalizationPolicy:
    max_input_bytes: int = 5 * 1024 * 1024
    max_normalized_chars: int = DEFAULT_MAX_NORMALIZED_CHARS
    max_json_text_values: int = DEFAULT_MAX_JSON_TEXT_VALUES

    def __post_init__(self) -> None:
        if self.max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be positive")
        if self.max_normalized_chars <= 0:
            raise ValueError("max_normalized_chars must be positive")
        if self.max_json_text_values <= 0:
            raise ValueError("max_json_text_values must be positive")


@dataclass(frozen=True)
class NormalizedContentRecord:
    normalization_id: str
    acquisition_id: str
    source_id: str | None
    discovery_result_id: str
    source_locator: str
    content_type: str
    raw_content_sha256: str
    normalized_text_sha256: str | None
    normalized_text: str
    normalized_char_count: int
    status: ContentNormalizationStatus
    failure_kind: NormalizationFailureKind | None = None
    error_message: str | None = None
    eligible_for_claim_extraction: bool = False
    external_content_policy: str = "evidence-not-instruction"
    content_instructions_executed: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CONTENT_NORMALIZATION_SCHEMA_VERSION,
            "normalization_id": self.normalization_id,
            "acquisition_id": self.acquisition_id,
            "source_id": self.source_id,
            "discovery_result_id": self.discovery_result_id,
            "source_locator": self.source_locator,
            "content_type": self.content_type,
            "raw_content_sha256": self.raw_content_sha256,
            "normalized_text_sha256": self.normalized_text_sha256,
            "normalized_text": self.normalized_text,
            "normalized_char_count": self.normalized_char_count,
            "status": self.status.value,
            "failure_kind": self.failure_kind.value if self.failure_kind else None,
            "error_message": self.error_message,
            "eligible_for_claim_extraction": self.eligible_for_claim_extraction,
            "external_content_policy": self.external_content_policy,
            "content_instructions_executed": self.content_instructions_executed,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def canonical_normalization_id(*, acquisition_id: str, raw_content_sha256: str, content_type: str) -> str:
    if not acquisition_id.startswith("content-acquisition:"):
        raise ValueError("invalid acquisition_id")
    encoded = json.dumps(
        {
            "acquisition_id": acquisition_id,
            "raw_content_sha256": raw_content_sha256.lower(),
            "content_type": content_type.lower(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"content-normalization:{hashlib.sha256(encoded).hexdigest()}"


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "nav", "noscript", "svg", "canvas"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "nav", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _collapse_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.replace("\x00", " ")).strip()


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _json_text_values(value: object, *, limit: int) -> Iterable[str]:
    count = 0
    stack = [value]
    while stack and count < limit:
        item = stack.pop(0)
        if isinstance(item, str):
            text = _collapse_text(item)
            if text:
                count += 1
                yield text
        elif isinstance(item, Mapping):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


class SafeContentNormalizer:
    def __init__(self, policy: NormalizationPolicy | None = None) -> None:
        self.policy = policy or NormalizationPolicy()

    def normalize(self, acquisition: ContentAcquisitionRecord, content: bytes) -> NormalizedContentRecord:
        content_type = (acquisition.content_type or "").split(";", 1)[0].strip().lower()
        digest = hashlib.sha256(content).hexdigest()
        normalization_id = canonical_normalization_id(
            acquisition_id=acquisition.acquisition_id,
            raw_content_sha256=digest,
            content_type=content_type or "unknown",
        )

        if acquisition.status is not ContentAcquisitionStatus.ACQUIRED or not acquisition.actual_source_body_fetched:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.ACQUISITION_NOT_ELIGIBLE,
                "only acquired source bodies can be normalized",
            )

        if len(content) > self.policy.max_input_bytes:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.SIZE_EXCEEDED,
                "content exceeds normalization byte budget",
            )

        try:
            text = self._normalize_by_type(content_type, content)
        except json.JSONDecodeError as exc:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.INVALID_JSON,
                str(exc),
            )
        except NotImplementedError as exc:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.PDF_TEXT_UNAVAILABLE,
                str(exc),
                status=ContentNormalizationStatus.UNSUPPORTED,
            )
        except ValueError as exc:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.MIME_UNSUPPORTED,
                str(exc),
                status=ContentNormalizationStatus.UNSUPPORTED,
            )

        normalized = _collapse_text(text)
        if not normalized:
            return self._failure(
                acquisition,
                normalization_id,
                digest,
                content_type,
                NormalizationFailureKind.EMPTY_TEXT,
                "normalized text is empty",
            )

        if len(normalized) > self.policy.max_normalized_chars:
            normalized = normalized[: self.policy.max_normalized_chars].rstrip()

        text_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return NormalizedContentRecord(
            normalization_id=normalization_id,
            acquisition_id=acquisition.acquisition_id,
            source_id=acquisition.source_id,
            discovery_result_id=acquisition.discovery_result_id,
            source_locator=acquisition.source_locator,
            content_type=content_type,
            raw_content_sha256=digest,
            normalized_text_sha256=text_digest,
            normalized_text=normalized,
            normalized_char_count=len(normalized),
            status=ContentNormalizationStatus.NORMALIZED,
            eligible_for_claim_extraction=True,
        )

    def _normalize_by_type(self, content_type: str, content: bytes) -> str:
        if content_type == "text/plain":
            return _decode_utf8(content)
        if content_type == "text/html":
            parser = _TextHTMLParser()
            parser.feed(_decode_utf8(content))
            return " ".join(parser.parts)
        if content_type == "application/json":
            payload = json.loads(_decode_utf8(content))
            return "\n".join(_json_text_values(payload, limit=self.policy.max_json_text_values))
        if content_type == "application/pdf":
            raise NotImplementedError("safe PDF text extraction is not configured")
        raise ValueError(f"unsupported content type: {content_type or 'missing'}")

    def _failure(
        self,
        acquisition: ContentAcquisitionRecord,
        normalization_id: str,
        digest: str,
        content_type: str,
        kind: NormalizationFailureKind,
        message: str,
        *,
        status: ContentNormalizationStatus = ContentNormalizationStatus.FAILED,
    ) -> NormalizedContentRecord:
        return NormalizedContentRecord(
            normalization_id=normalization_id,
            acquisition_id=acquisition.acquisition_id,
            source_id=acquisition.source_id,
            discovery_result_id=acquisition.discovery_result_id,
            source_locator=acquisition.source_locator,
            content_type=content_type or "unknown",
            raw_content_sha256=digest,
            normalized_text_sha256=None,
            normalized_text="",
            normalized_char_count=0,
            status=status,
            failure_kind=kind,
            error_message=message,
        )


def _fixture_acquisition(content_type: str = "text/html") -> ContentAcquisitionRecord:
    return ContentAcquisitionRecord(
        acquisition_id="content-acquisition:" + "a" * 64,
        discovery_result_id="discovery-result:test",
        source_locator="https://example.invalid/research",
        content_url="https://example.invalid/research",
        final_url="https://example.invalid/research",
        content_type=content_type,
        byte_count=1,
        content_sha256="0" * 64,
        status=ContentAcquisitionStatus.ACQUIRED,
        failure_kind=None,
        error_message=None,
        source_id="source:" + "b" * 64,
        raw_path=None,
        metadata_path=None,
        actual_source_body_fetched=True,
        stored_as_inert_evidence=True,
    )


def content_normalization_release_check() -> Mapping[str, object]:
    normalizer = SafeContentNormalizer(NormalizationPolicy(max_normalized_chars=10_000))
    html = normalizer.normalize(
        _fixture_acquisition("text/html"),
        b"<html><nav>menu</nav><script>alert(1)</script><article>Breakout improves robustness.</article></html>",
    )
    json_record = normalizer.normalize(
        _fixture_acquisition("application/json"),
        b'{"title":"Metadata", "abstract":"Momentum claims require evidence."}',
    )
    pdf = normalizer.normalize(_fixture_acquisition("application/pdf"), b"%PDF-1.4\nfixture")

    checks = {
        "html_normalized": html.status is ContentNormalizationStatus.NORMALIZED and "alert" not in html.normalized_text and "Breakout improves robustness." in html.normalized_text,
        "json_normalized": json_record.status is ContentNormalizationStatus.NORMALIZED and "Momentum claims require evidence." in json_record.normalized_text,
        "pdf_fail_closed": pdf.status is ContentNormalizationStatus.UNSUPPORTED and not pdf.eligible_for_claim_extraction,
        "claim_eligible_only_after_success": html.eligible_for_claim_extraction and not pdf.eligible_for_claim_extraction,
        "knowledge_not_validated": not html.knowledge_validated and not json_record.knowledge_validated,
        "production_not_approved": not html.production_approved and not json_record.production_approved,
        "instructions_not_executed": not html.content_instructions_executed and not json_record.content_instructions_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"content normalization release check failed: {failed}")
    return {
        "schema_version": CONTENT_NORMALIZATION_SCHEMA_VERSION,
        "normalized": 2,
        "unsupported": 1,
        "checks": checks,
        "safety": "pass",
    }


def _main() -> int:
    parser = argparse.ArgumentParser(prog="python -m gaon.knowledge.content_normalization")
    parser.add_argument("command", choices=("release-check",))
    args = parser.parse_args()
    if args.command == "release-check":
        payload = content_normalization_release_check()
        print(
            "gaon-content-normalization-release-check: PASS "
            f"schema_version={payload['schema_version']} "
            f"normalized={payload['normalized']} unsupported={payload['unsupported']} "
            "eligible_claims=true knowledge_validated=false production_approved=false safety=pass"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
