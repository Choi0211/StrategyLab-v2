"""Experience pattern records for Gaon."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from gaon.learning.evidence.models import EvidenceRecord


class ExperienceType(str, Enum):
    """Learned experience category."""

    SUCCESS_PATTERN = "success_pattern"
    FAILURE_REASON = "failure_reason"
    USER_PREFERENCE = "user_preference"


@dataclass(frozen=True)
class ExperiencePattern:
    """Evidence-backed experience record."""

    experience_id: str
    experience_type: ExperienceType
    description: str
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.experience_id:
            raise ValueError("experience_id is required")
        if not self.description:
            raise ValueError("description is required")
        if not self.evidence:
            raise ValueError("experience requires evidence")
