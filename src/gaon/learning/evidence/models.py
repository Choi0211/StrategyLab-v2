"""Evidence records for Gaon's learning loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceType(str, Enum):
    """Allowed evidence categories."""

    SOURCE = "source"
    URL = "url"
    DOCUMENT = "document"
    RESEARCH = "research"
    PAPER = "paper"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    BACKTEST = "backtest"
    EXPERIMENT = "experiment"


@dataclass(frozen=True)
class EvidenceRecord:
    """Evidence attached to knowledge, memory, or policy candidates."""

    evidence_id: str
    evidence_type: EvidenceType
    reference: str
    summary: str

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id is required")
        if not self.reference:
            raise ValueError("evidence reference is required")
        if not self.summary:
            raise ValueError("evidence summary is required")
