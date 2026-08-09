"""Sprint 184 - Promotion Candidate Gate.

Creates approval-required promotion candidate records from robustness rankings
without applying strategy changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

from .robustness_ranking import (
    RobustnessRankingResult,
    RobustnessRankingStatus,
    RobustnessRankedStrategy,
    robustness_ranking_release_check,
)


PROMOTION_GATE_SCHEMA_VERSION = 1


class PromotionGateStatus(str, Enum):
    REQUIRES_HUMAN_APPROVAL = "requires_human_approval"
    BLOCKED = "blocked"


class PromotionGateBlocker(str, Enum):
    RANKING_NOT_READY = "ranking_not_ready"
    NO_RANKED_STRATEGY = "no_ranked_strategy"
    TOP_CANDIDATE_NOT_ELIGIBLE = "top_candidate_not_eligible"
    FIXTURE_BACKED_PRODUCTION_BLOCK = "fixture_backed_production_block"


@dataclass(frozen=True)
class PromotionCandidateRecord:
    candidate_id: str
    experiment_id: str
    evidence_id: str
    score: float
    rank: int
    source: str
    fixture_backed: bool
    approval_required: bool
    rollback_target: str
    status: PromotionGateStatus
    blockers: tuple[PromotionGateBlocker, ...]
    automatic_champion_promotion: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": PROMOTION_GATE_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "experiment_id": self.experiment_id,
            "evidence_id": self.evidence_id,
            "score": self.score,
            "rank": self.rank,
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "approval_required": self.approval_required,
            "rollback_target": self.rollback_target,
            "status": self.status.value,
            "blockers": [item.value for item in self.blockers],
            "automatic_champion_promotion": self.automatic_champion_promotion,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class PromotionCandidateGate:
    def evaluate(
        self,
        ranking: RobustnessRankingResult,
        *,
        rollback_target: str,
        allow_fixture: bool = False,
    ) -> PromotionCandidateRecord:
        blockers: list[PromotionGateBlocker] = []
        top: RobustnessRankedStrategy | None = None
        if ranking.status is not RobustnessRankingStatus.RANKED:
            blockers.append(PromotionGateBlocker.RANKING_NOT_READY)
        if ranking.ranked:
            top = ranking.ranked[0]
        else:
            blockers.append(PromotionGateBlocker.NO_RANKED_STRATEGY)
        if top is not None and not top.eligible_for_review:
            blockers.append(PromotionGateBlocker.TOP_CANDIDATE_NOT_ELIGIBLE)
        if top is not None and top.fixture_backed and not allow_fixture:
            blockers.append(PromotionGateBlocker.FIXTURE_BACKED_PRODUCTION_BLOCK)

        status = (
            PromotionGateStatus.BLOCKED
            if blockers
            else PromotionGateStatus.REQUIRES_HUMAN_APPROVAL
        )
        if top is None:
            top = RobustnessRankedStrategy(
                rank=0,
                experiment_id="",
                evidence_id="",
                score=0.0,
                trade_count=0,
                total_return=0.0,
                mdd=0.0,
                profit_factor=0.0,
                win_rate=0.0,
                source="none",
                fixture_backed=False,
                eligible_for_review=False,
            )
        return PromotionCandidateRecord(
            candidate_id=_candidate_id(top),
            experiment_id=top.experiment_id,
            evidence_id=top.evidence_id,
            score=top.score,
            rank=top.rank,
            source=top.source,
            fixture_backed=top.fixture_backed,
            approval_required=True,
            rollback_target=rollback_target,
            status=status,
            blockers=tuple(dict.fromkeys(blockers)),
        )


def _candidate_id(top: RobustnessRankedStrategy) -> str:
    encoded = json.dumps(
        {
            "experiment_id": top.experiment_id,
            "evidence_id": top.evidence_id,
            "score": top.score,
            "rank": top.rank,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"promotion-candidate:{hashlib.sha256(encoded).hexdigest()}"


def promotion_candidate_gate_release_check() -> Mapping[str, object]:
    ranking_payload = robustness_ranking_release_check()
    from .robustness_ranking import RobustnessRankingResult, RobustnessRankingStatus, RobustnessRankedStrategy

    ranked = RobustnessRankingResult(
        status=RobustnessRankingStatus.RANKED,
        blockers=(),
        ranked=(
            RobustnessRankedStrategy(
                rank=1,
                experiment_id="strategy-experiment:release",
                evidence_id="validation-evidence:release",
                score=4.2,
                trade_count=60,
                total_return=0.18,
                mdd=0.09,
                profit_factor=1.6,
                win_rate=0.56,
                source="real:yahoo-chart",
                fixture_backed=False,
            ),
        ),
        warnings=(),
    )
    candidate = PromotionCandidateGate().evaluate(
        ranked,
        rollback_target="strategy-config:default:active",
    )
    fixture_block = PromotionCandidateGate().evaluate(
        RobustnessRankingResult(
            status=RobustnessRankingStatus.RANKED,
            blockers=(),
            ranked=(
                RobustnessRankedStrategy(
                    rank=1,
                    experiment_id="strategy-experiment:fixture",
                    evidence_id="validation-evidence:fixture",
                    score=5.0,
                    trade_count=60,
                    total_return=0.18,
                    mdd=0.09,
                    profit_factor=1.6,
                    win_rate=0.56,
                    source="fixture:promotion-gate",
                    fixture_backed=True,
                ),
            ),
            warnings=(),
        ),
        rollback_target="strategy-config:default:active",
    )
    checks = {
        "ranking_ready": ranking_payload["status"] == "ranked",
        "requires_approval": candidate.status is PromotionGateStatus.REQUIRES_HUMAN_APPROVAL,
        "approval_required": candidate.approval_required,
        "fixture_blocked": PromotionGateBlocker.FIXTURE_BACKED_PRODUCTION_BLOCK in fixture_block.blockers,
        "no_promotion": not candidate.automatic_champion_promotion,
        "no_mutation": not candidate.strategy_mutated and not candidate.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"promotion candidate gate release check failed: {failed}")
    return {
        "schema_version": PROMOTION_GATE_SCHEMA_VERSION,
        "status": candidate.status.value,
        "approval_required": candidate.approval_required,
        "candidate_id": candidate.candidate_id,
        "checks": checks,
        "safety": "pass",
    }
