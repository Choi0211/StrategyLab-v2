"""Gaon external knowledge contracts.

External content is untrusted evidence, never instruction.
"""

from .provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
    canonical_source_id,
)

__all__ = [
    "SourceProvenance",
    "SourceType",
    "TrustLevel",
    "canonical_source_id",
]
