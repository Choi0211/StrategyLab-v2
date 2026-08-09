"""Sprint 180 - Evidence-backed Strategy Hypothesis.

Creates PROPOSED strategy hypotheses from unvalidated external research memory.

Safety invariants:
- hypothesis is not a tested strategy
- no performance metric may be fabricated
- evidence references are mandatory
- no production approval, policy application, strategy mutation, or trading
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable, Mapping

from .external_research_memory import ExternalResearchMemoryRecord


EVIDENCE_HYPOTHESIS_SCHEMA_VERSION = 1

_FORBIDDEN_PERFORMANCE_TOKENS = (
    "return=",
    "mdd=",
    "profit_factor=",
    "sharpe=",
    "win_rate=",
    "cagr=",
    "trade_count=",
    "%",
)


class StrategyHypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"


class StrategyHypothesisBlocker(str, Enum):
    NO_MEMORY = "no_memory"
    MISSING_EVIDENCE = "missing_evidence"
    FABRICATED_METRIC = "fabricated_metric"
    PREVALIDATED_MEMORY = "prevalidated_memory"


@dataclass(frozen=True)
class EvidenceBackedStrategyHypothesis:
    hypothesis_id: str
    topic_key: str
    status: StrategyHypothesisStatus
    changed_rules: tuple[str, ...]
    rationale: str
    mechanism: str
    evidence_memory_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    question_ids: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    blockers: tuple[StrategyHypothesisBlocker, ...] = ()
    tested: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    policy_applied: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EVIDENCE_HYPOTHESIS_SCHEMA_VERSION,
            "hypothesis_id": self.hypothesis_id,
            "topic_key": self.topic_key,
            "status": self.status.value,
            "changed_rules": list(self.changed_rules),
            "rationale": self.rationale,
            "mechanism": self.mechanism,
            "evidence_memory_ids": list(self.evidence_memory_ids),
            "claim_ids": list(self.claim_ids),
            "question_ids": list(self.question_ids),
            "falsification_criteria": list(self.falsification_criteria),
            "blockers": [item.value for item in self.blockers],
            "tested": self.tested,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "policy_applied": self.policy_applied,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def canonical_hypothesis_id(
    *,
    topic_key: str,
    memory_ids: Iterable[str],
    changed_rules: Iterable[str],
) -> str:
    encoded = json.dumps(
        {
            "topic_key": topic_key.strip().lower(),
            "memory_ids": sorted(memory_ids),
            "changed_rules": sorted(rule.strip() for rule in changed_rules),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"strategy-hypothesis:{hashlib.sha256(encoded).hexdigest()}"


class EvidenceBackedHypothesisGenerator:
    def generate(
        self,
        *,
        topic_key: str,
        memories: tuple[ExternalResearchMemoryRecord, ...],
        changed_rules: tuple[str, ...],
        rationale: str,
        mechanism: str,
        falsification_criteria: tuple[str, ...],
    ) -> EvidenceBackedStrategyHypothesis:
        blockers = self._blockers(
            memories,
            changed_rules,
            rationale,
            mechanism,
            falsification_criteria,
        )
        memory_ids = tuple(record.memory_id for record in memories)
        hypothesis_id = canonical_hypothesis_id(
            topic_key=topic_key,
            memory_ids=memory_ids,
            changed_rules=changed_rules,
        )
        if blockers:
            return EvidenceBackedStrategyHypothesis(
                hypothesis_id=hypothesis_id,
                topic_key=topic_key.strip().lower(),
                status=StrategyHypothesisStatus.BLOCKED,
                changed_rules=changed_rules,
                rationale=rationale,
                mechanism=mechanism,
                evidence_memory_ids=memory_ids,
                claim_ids=(),
                question_ids=(),
                falsification_criteria=falsification_criteria,
                blockers=tuple(blockers),
            )

        claim_ids = tuple(
            sorted({claim_id for record in memories for claim_id in record.claim_ids})
        )
        question_ids = tuple(
            sorted({
                question_id
                for record in memories
                for question_id in record.question_ids
            })
        )
        return EvidenceBackedStrategyHypothesis(
            hypothesis_id=hypothesis_id,
            topic_key=topic_key.strip().lower(),
            status=StrategyHypothesisStatus.PROPOSED,
            changed_rules=changed_rules,
            rationale=rationale,
            mechanism=mechanism,
            evidence_memory_ids=memory_ids,
            claim_ids=claim_ids,
            question_ids=question_ids,
            falsification_criteria=falsification_criteria,
        )

    @staticmethod
    def _blockers(
        memories: tuple[ExternalResearchMemoryRecord, ...],
        changed_rules: tuple[str, ...],
        rationale: str,
        mechanism: str,
        falsification_criteria: tuple[str, ...],
    ) -> list[StrategyHypothesisBlocker]:
        blockers: list[StrategyHypothesisBlocker] = []
        if not memories:
            blockers.append(StrategyHypothesisBlocker.NO_MEMORY)
        if any(
            not record.claim_ids or not record.source_ids
            for record in memories
        ):
            blockers.append(StrategyHypothesisBlocker.MISSING_EVIDENCE)
        if any(
            record.knowledge_validated
            or record.production_approved
            or record.policy_applied
            or record.strategy_mutated
            or record.order_executed
            for record in memories
        ):
            blockers.append(StrategyHypothesisBlocker.PREVALIDATED_MEMORY)
        text = " ".join((*changed_rules, rationale, mechanism, *falsification_criteria)).casefold()
        if any(token in text for token in _FORBIDDEN_PERFORMANCE_TOKENS):
            blockers.append(StrategyHypothesisBlocker.FABRICATED_METRIC)
        return blockers


def evidence_backed_hypothesis_release_check() -> Mapping[str, object]:
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:release-check",
        fingerprint="f" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:release-check",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a", "claim:b"),
        question_ids=("research-question:a",),
        source_ids=("source:a", "source:b"),
        created_at="2026-08-08T00:00:00+00:00",
    )
    generator = EvidenceBackedHypothesisGenerator()
    hypothesis = generator.generate(
        topic_key="strategy.breakout.robustness",
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="Evidence conflict suggests breakout robustness may depend on regime context.",
        mechanism="Regime filtering narrows entries to conditions aligned with supporting evidence.",
        falsification_criteria=("Reject if independent backtest evidence does not improve robustness.",),
    )
    blocked = generator.generate(
        topic_key="strategy.breakout.robustness",
        memories=(memory,),
        changed_rules=("expect return=12%",),
        rationale="fabricated metric should block",
        mechanism="no tested evidence",
        falsification_criteria=("Reject if mdd=5%.",),
    )

    checks = {
        "proposed": hypothesis.status is StrategyHypothesisStatus.PROPOSED,
        "evidence_linked": hypothesis.claim_ids == ("claim:a", "claim:b")
        and hypothesis.evidence_memory_ids == (memory.memory_id,),
        "falsifiable": len(hypothesis.falsification_criteria) == 1,
        "not_tested": not hypothesis.tested,
        "not_validated": not hypothesis.knowledge_validated,
        "not_production": not hypothesis.production_approved,
        "no_mutation": not hypothesis.strategy_mutated
        and not hypothesis.order_executed,
        "fabricated_metric_blocked":
            blocked.status is StrategyHypothesisStatus.BLOCKED
            and StrategyHypothesisBlocker.FABRICATED_METRIC in blocked.blockers,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"evidence-backed hypothesis release check failed: {failed}"
        )

    return {
        "schema_version": EVIDENCE_HYPOTHESIS_SCHEMA_VERSION,
        "status": hypothesis.status.value,
        "claim_refs": len(hypothesis.claim_ids),
        "memory_refs": len(hypothesis.evidence_memory_ids),
        "checks": checks,
        "safety": "pass",
    }

