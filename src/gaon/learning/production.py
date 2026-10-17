"""Durable production learning loop for Gaon's autonomous research.

Learning is advisory. It may rank future research hypotheses and preserve
lessons, but it can never approve/promote a strategy, change deployment
configuration, place an order, or bypass a human gate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import sqlite3
from typing import Mapping

from gaon.learning.confidence.models import ConfidenceScore
from gaon.learning.contracts import (
    AuditAction,
    AuditEvent,
    LearningRecord,
    LearningRecordType,
    RevalidationSchedule,
    RevalidationStatus,
)
from gaon.learning.detection import DuplicateDetector
from gaon.learning.evidence.models import EvidenceRecord, EvidenceType
from gaon.learning.retrieval import RelatedMemoryQuery, RelatedMemoryResult, RelatedMemoryRetriever
from gaon.knowledge.strategy_candidate import (
    PASS_LIKE_STAGE_STATUSES,
    EconomicViabilityStatus,
    StrategyCandidateRecord,
    StrategyCandidateStatus,
    candidate_cumulative_performance,
    evaluate_economic_viability,
)

LEARNING_SCOPE = "gaon"
LEARNING_PROJECT = "StrategyLab-v2"
REVALIDATION_DAYS = 30
MAX_EVIDENCE_PER_RECORD = 48


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _due_at(now: str) -> str:
    return (_parse_utc(now) + timedelta(days=REVALIDATION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _due_at_days(now: str, days: int) -> str:
    return (_parse_utc(now) + timedelta(days=max(1, int(days)))).strftime("%Y-%m-%dT%H:%M:%SZ")


class SQLiteLearningRepository:
    """SQLite-backed repository for the existing LearningRecord contract."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._duplicates = DuplicateDetector()
        self._retriever = RelatedMemoryRetriever()

    def exists(self, record_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM learning_records WHERE record_id=?", (record_id,)
        ).fetchone() is not None

    def get(self, record_id: str) -> LearningRecord:
        row = self._connection.execute(
            "SELECT payload_json FROM learning_records WHERE record_id=?", (record_id,)
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return LearningRecord.from_json(str(row[0]))

    def add(self, record: LearningRecord) -> None:
        if self.exists(record.record_id):
            raise ValueError(f"duplicate record_id: {record.record_id}")
        self._write_current(record, insert_only=True)

    def upsert(self, record: LearningRecord) -> bool:
        """Persist a new record/version; identical state is a no-op."""
        existing = self.get(record.record_id) if self.exists(record.record_id) else None
        if existing is not None:
            if _learning_material_key(existing) == _learning_material_key(record):
                return False
            if record.version <= existing.version:
                record = replace(record, version=existing.version + 1, created_at=existing.created_at)
        self._write_current(record, insert_only=existing is None)
        return True

    def _write_current(self, record: LearningRecord, *, insert_only: bool) -> None:
        payload = record.to_json()
        with self._connection:
            if insert_only:
                self._connection.execute(
                    """
                    INSERT INTO learning_records(
                        record_id,record_type,scope,project,strategy,market,confidence,
                        conflict_penalty,version,payload_json,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        record.record_id, record.record_type.value, record.scope, record.project,
                        record.strategy, record.market, record.confidence.value,
                        record.confidence.conflict_penalty, record.version, payload,
                        record.created_at, record.updated_at,
                    ),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE learning_records SET
                        record_type=?,scope=?,project=?,strategy=?,market=?,confidence=?,
                        conflict_penalty=?,version=?,payload_json=?,updated_at=?
                    WHERE record_id=?
                    """,
                    (
                        record.record_type.value, record.scope, record.project, record.strategy,
                        record.market, record.confidence.value, record.confidence.conflict_penalty,
                        record.version, payload, record.updated_at, record.record_id,
                    ),
                )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO learning_record_versions(record_id,version,payload_json,created_at)
                VALUES (?,?,?,?)
                """,
                (record.record_id, record.version, payload, record.updated_at),
            )

    def list_all(self) -> tuple[LearningRecord, ...]:
        rows = self._connection.execute(
            "SELECT payload_json FROM learning_records ORDER BY created_at,record_id"
        ).fetchall()
        return tuple(LearningRecord.from_json(str(row[0])) for row in rows)

    def list_chronological(self) -> tuple[LearningRecord, ...]:
        return self.list_all()

    def filter(
        self,
        *,
        scope: str | None = None,
        project: str | None = None,
        strategy: str | None = None,
        market: str | None = None,
        record_type: LearningRecordType | None = None,
    ) -> tuple[LearningRecord, ...]:
        records = self.list_all()
        if scope is not None:
            records = tuple(x for x in records if x.scope == scope)
        if project is not None:
            records = tuple(x for x in records if x.project == project)
        if strategy is not None:
            records = tuple(x for x in records if x.strategy == strategy)
        if market is not None:
            records = tuple(x for x in records if x.market == market)
        if record_type is not None:
            records = tuple(x for x in records if x.record_type is record_type)
        return records

    def find_duplicates(self, candidate: LearningRecord):
        return self._duplicates.find(candidate, self.list_all())

    def retrieve_related(self, query: RelatedMemoryQuery) -> tuple[RelatedMemoryResult, ...]:
        return self._retriever.retrieve(query, self.list_all())

    def append_audit(self, event: AuditEvent) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO learning_audit_events(event_id,target_ref,action,payload_json,created_at)
                VALUES (?,?,?,?,?)
                """,
                (event.event_id, event.target_ref, event.action.value, event.to_json(), event.timestamp),
            )

    def list_audit(self, target_ref: str | None = None, action: AuditAction | None = None) -> tuple[AuditEvent, ...]:
        sql = "SELECT payload_json FROM learning_audit_events"
        clauses: list[str] = []
        params: list[object] = []
        if target_ref is not None:
            clauses.append("target_ref=?"); params.append(target_ref)
        if action is not None:
            clauses.append("action=?"); params.append(action.value)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at,event_id"
        rows = self._connection.execute(sql, tuple(params)).fetchall()
        return tuple(AuditEvent.from_json(str(row[0])) for row in rows)

    # Learning claims remain approval-gated elsewhere. Production candidate
    # lessons are LearningRecords, never automatically validated claims.
    def list_claims(self) -> tuple[object, ...]:
        return ()


@dataclass(frozen=True)
class FamilyLearningPrior:
    family: str
    score: float
    record_count: int
    success_count: int
    failure_count: int
    mean_confidence: float
    conflict_penalty: float

    def to_json(self) -> dict[str, object]:
        return {
            "family": self.family,
            "score": self.score,
            "record_count": self.record_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "mean_confidence": self.mean_confidence,
            "conflict_penalty": self.conflict_penalty,
        }


@dataclass(frozen=True)
class LearningUpdateResult:
    written: bool
    record_id: str | None
    version: int | None
    record_type: str | None
    confidence: float | None
    conflict_penalty: float | None
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "written": self.written,
            "record_id": self.record_id,
            "version": self.version,
            "record_type": self.record_type,
            "confidence": self.confidence,
            "conflict_penalty": self.conflict_penalty,
            "reason": self.reason,
            "automatic_promotion": False,
            "strategy_mutated": False,
            "order_executed": False,
        }


class ProductionLearningEngine:
    """Converts real candidate/operation outcomes into durable lessons."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.repository = SQLiteLearningRepository(connection)

    def learn_candidate(self, mission, candidate: StrategyCandidateRecord, *, now: str) -> LearningUpdateResult:
        evidence = _candidate_evidence(candidate)
        if not evidence:
            return LearningUpdateResult(False, None, None, None, None, None, "no_material_evidence")
        performance = candidate_cumulative_performance(candidate)
        viability = evaluate_economic_viability(candidate)
        record_type, outcome = _candidate_record_type(candidate, viability.status)
        record_id = f"learning:candidate:{_stable_id(mission.mission_id, candidate.candidate_id)}"
        previous = self.repository.get(record_id) if self.repository.exists(record_id) else None
        opposite = self._opposite_family_records(
            family=candidate.strategy_family,
            market=str(mission.market),
            record_type=record_type,
            exclude_id=record_id,
        )
        conflict_penalty = min(0.55, 0.15 * len(opposite))
        confidence = _candidate_confidence(candidate, conflict_penalty=conflict_penalty)
        content = _candidate_lesson_content(candidate, performance, viability.status, viability.reason, outcome)
        version = (previous.version + 1) if previous is not None else 1
        record = LearningRecord(
            record_id=record_id,
            record_type=record_type,
            content=content,
            scope=LEARNING_SCOPE,
            project=LEARNING_PROJECT,
            strategy=candidate.strategy_family,
            market=str(mission.market),
            created_at=previous.created_at if previous else now,
            updated_at=now,
            version=version,
            evidence=evidence,
            confidence=confidence,
            revalidation=RevalidationSchedule(
                schedule_id=f"revalidation:{record_id}",
                target_ref=record_id,
                reason="candidate lesson must be rechecked against future market evidence",
                due_at=_due_at(now),
                frequency="monthly",
                status=RevalidationStatus.PENDING,
                scope=LEARNING_SCOPE,
                project=LEARNING_PROJECT,
                strategy=candidate.strategy_family,
                market=str(mission.market),
            ),
            audit_ref=f"audit:{record_id}:v{version}",
        )
        written = self.repository.upsert(record)
        current = self.repository.get(record_id) if written else previous or record
        if written:
            self.repository.append_audit(_audit_for(current, previous, now))
        return LearningUpdateResult(
            written, current.record_id, current.version, current.record_type.value,
            current.confidence.value, current.confidence.conflict_penalty,
            outcome if written else "unchanged",
        )

    def sync_operational_feedback(self, feedback, *, now: str) -> LearningUpdateResult:
        if feedback is None:
            return LearningUpdateResult(False, None, None, None, None, None, "operational_feedback_unavailable")
        payload = feedback.to_json() if hasattr(feedback, "to_json") else dict(feedback)
        self._sync_operational_strategy_records(payload, now=now)
        completed = int(payload.get("completed_trade_count") or 0)
        commission_obs = int(payload.get("commission_observation_count") or 0)
        if completed <= 0 and commission_obs <= 0:
            return LearningUpdateResult(False, None, None, None, None, None, "operational_sample_empty")
        market = str(payload.get("market") or "UNKNOWN")
        rate = payload.get("observed_commission_rate")
        slippage_obs = int(payload.get("slippage_observation_count") or 0)
        partial = int(payload.get("partial_fill_count") or 0)
        pnl = payload.get("total_realized_pnl")
        record_id = f"learning:operational:{market}:execution-cost"
        previous = self.repository.get(record_id) if self.repository.exists(record_id) else None
        evidence = (
            EvidenceRecord(
                f"evidence:{_stable_id(record_id, str(completed), str(commission_obs), str(rate))}",
                EvidenceType.EXPERIMENT,
                f"runtime:{market}:paper-live-execution",
                f"completed_trades={completed}; commission_fill_observations={commission_obs}; partial_fills={partial}; slippage_observations={slippage_obs}",
            ),
        )
        confidence_value = min(0.9, 0.35 + 0.1 * math.log10(max(completed, 1) + 1) + 0.15 * min(commission_obs / 100.0, 1.0))
        if slippage_obs == 0:
            confidence_value = min(confidence_value, 0.72)
        content = (
            f"execution_cost_observation market={market}; completed_trades={completed}; "
            f"observed_commission_rate={rate if rate is not None else 'unknown'}; "
            f"commission_observations={commission_obs}; slippage_observations={slippage_obs}; "
            f"partial_fills={partial}; total_realized_pnl={pnl if pnl is not None else 'unknown'}; "
            f"cost_model_match={'unconfirmed' if slippage_obs == 0 else 'requires_comparison'}"
        )
        version = previous.version + 1 if previous else 1
        record = LearningRecord(
            record_id=record_id,
            record_type=LearningRecordType.RESEARCH_OUTCOME,
            content=content,
            scope=LEARNING_SCOPE,
            project=LEARNING_PROJECT,
            strategy="execution-cost",
            market=market,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            version=version,
            evidence=evidence,
            confidence=ConfidenceScore(
                round(confidence_value, 6),
                "direct Paper/Live execution observations; cost-model match remains unconfirmed until slippage is measured and compared",
                evidence_count=max(completed, commission_obs),
                validation_state="need_validation",
                recency=1.0,
                conflict_penalty=0.0,
            ),
            revalidation=RevalidationSchedule(
                schedule_id=f"revalidation:{record_id}", target_ref=record_id,
                reason="execution costs change with venue/liquidity and require fresh observations",
                due_at=_due_at(now), frequency="monthly", status=RevalidationStatus.PENDING,
                scope=LEARNING_SCOPE, project=LEARNING_PROJECT, strategy="execution-cost", market=market,
            ),
            audit_ref=f"audit:{record_id}:v{version}",
        )
        written = self.repository.upsert(record)
        current = self.repository.get(record_id) if written else previous or record
        if written:
            self.repository.append_audit(_audit_for(current, previous, now))
        return LearningUpdateResult(
            written, current.record_id, current.version, current.record_type.value,
            current.confidence.value, current.confidence.conflict_penalty,
            "operational_feedback_updated" if written else "unchanged",
        )

    def _sync_operational_strategy_records(self, payload: Mapping[str, object], *, now: str) -> int:
        """Persist direct strategy-attributed execution outcomes as advisory memory.

        These records are intentionally ``RESEARCH_OUTCOME`` regardless of
        PnL sign. A few profitable or losing real trades are observations,
        not proof of a reusable research success/failure pattern. Runtime
        strategy records are excluded from research-family priors below.
        """
        market = str(payload.get("market") or "UNKNOWN")
        raw = payload.get("strategy_performance")
        if not isinstance(raw, (list, tuple)):
            return 0
        identity_total = int(payload.get("strategy_identity_total_count") or 0)
        identity_observed = int(payload.get("strategy_identity_observation_count") or 0)
        coverage = identity_observed / identity_total if identity_total > 0 else 0.0
        writes = 0
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            strategy_id = str(item.get("strategy_id") or "").strip()
            mode = str(item.get("mode") or "unknown").strip().casefold()
            count = int(item.get("completed_trade_count") or 0)
            if not strategy_id or mode not in {"paper", "live"} or count <= 0:
                continue
            runtime_strategy = f"runtime:{mode}:{strategy_id}"
            record_id = f"learning:operational:{market}:strategy:{_stable_id(mode, strategy_id)}"
            previous = self.repository.get(record_id) if self.repository.exists(record_id) else None
            refs = item.get("evidence_refs")
            evidence: list[EvidenceRecord] = []
            if isinstance(refs, (list, tuple)):
                for ref in refs[:MAX_EVIDENCE_PER_RECORD]:
                    reference = str(ref or "").strip()
                    if not reference:
                        continue
                    evidence.append(EvidenceRecord(
                        f"evidence:{_stable_id(record_id, reference)}",
                        EvidenceType.EXPERIMENT,
                        reference,
                        f"direct {mode} closed-trade evidence for runtime strategy {strategy_id}",
                    ))
            if not evidence:
                evidence.append(EvidenceRecord(
                    f"evidence:{_stable_id(record_id, str(count), str(item.get('last_closed_at')))}",
                    EvidenceType.EXPERIMENT,
                    f"runtime:{market}:{mode}:{strategy_id}",
                    f"strategy-attributed closed trades={count}; archive identity explicitly observed",
                ))
            win_rate = item.get("win_rate")
            gross_pnl = item.get("total_realized_pnl")
            net_count = int(item.get("net_pnl_observation_count") or 0)
            net_pnl = item.get("observed_net_pnl_total")
            fee_count = int(item.get("fee_observation_count") or 0)
            fee_total = item.get("observed_fee_total")
            # Paper evidence is useful but capped below live evidence. Identity
            # coverage also affects confidence so partially-attributed history
            # cannot look more certain than it is.
            sample_component = 0.16 * min(math.log10(count + 1) / math.log10(31), 1.0)
            volume_component = 0.16 * min(count / 30.0, 1.0)
            coverage_component = 0.12 * min(max(coverage, 0.0), 1.0)
            confidence_value = 0.28 + sample_component + volume_component + coverage_component
            confidence_value = min(0.72 if mode == "paper" else 0.88, confidence_value)
            content = (
                f"runtime_strategy_observation market={market}; mode={mode}; strategy_id={strategy_id}; "
                f"completed_trades={count}; win_rate={win_rate if win_rate is not None else 'unknown'}; "
                f"gross_realized_pnl={gross_pnl if gross_pnl is not None else 'unknown'}; "
                f"net_pnl_observations={net_count}; observed_net_pnl={net_pnl if net_pnl is not None else 'unknown'}; "
                f"fee_observations={fee_count}; observed_fee_total={fee_total if fee_total is not None else 'unknown'}; "
                f"long_trades={int(item.get('long_trade_count') or 0)}; short_trades={int(item.get('short_trade_count') or 0)}; "
                f"identity_coverage={round(coverage, 6)}; identity_observed={identity_observed}; identity_total={identity_total}; "
                f"first_closed_at={item.get('first_closed_at') or 'unknown'}; last_closed_at={item.get('last_closed_at') or 'unknown'}; "
                "inference_scope=observational_only"
            )
            version = previous.version + 1 if previous else 1
            record = LearningRecord(
                record_id=record_id,
                record_type=LearningRecordType.RESEARCH_OUTCOME,
                content=content,
                scope=LEARNING_SCOPE, project=LEARNING_PROJECT,
                strategy=runtime_strategy, market=market,
                created_at=previous.created_at if previous else now, updated_at=now, version=version,
                evidence=tuple(evidence),
                confidence=ConfidenceScore(
                    round(confidence_value, 6),
                    f"direct {mode} strategy-attributed execution observations; observational only and never promotion authority",
                    evidence_count=count,
                    validation_state=f"{mode}_observed", recency=1.0, conflict_penalty=0.0,
                ),
                revalidation=RevalidationSchedule(
                    schedule_id=f"revalidation:{record_id}", target_ref=record_id,
                    reason="runtime strategy performance changes with market regime and requires fresh execution observations",
                    due_at=_due_at_days(now, 7), frequency="weekly", status=RevalidationStatus.PENDING,
                    scope=LEARNING_SCOPE, project=LEARNING_PROJECT, strategy=runtime_strategy, market=market,
                ),
                audit_ref=f"audit:{record_id}:v{version}",
            )
            written = self.repository.upsert(record)
            if written:
                current = self.repository.get(record_id)
                self.repository.append_audit(_audit_for(current, previous, now))
                writes += 1
        return writes

    def family_priors(self, *, market: str) -> dict[str, float]:
        return {item.family: item.score for item in self.family_prior_details(market=market)}

    def family_prior_details(self, *, market: str) -> tuple[FamilyLearningPrior, ...]:
        by_family: dict[str, list[LearningRecord]] = {}
        for record in self.repository.filter(scope=LEARNING_SCOPE, project=LEARNING_PROJECT, market=market):
            if record.strategy in {"execution-cost", "autonomous-research"} or record.strategy.startswith("runtime:"):
                continue
            by_family.setdefault(record.strategy, []).append(record)
        priors: list[FamilyLearningPrior] = []
        for family, records in by_family.items():
            successes = sum(r.record_type is LearningRecordType.SUCCESS_PATTERN for r in records)
            failures = sum(r.record_type is LearningRecordType.FAILURE_PATTERN for r in records)
            confidence = sum(r.confidence.value for r in records) / len(records)
            stored_conflict = sum(r.confidence.conflict_penalty for r in records) / len(records)
            structural_conflict = min(0.55, 0.15 * min(successes, failures)) if successes and failures else 0.0
            conflict = max(stored_conflict, structural_conflict)
            score = 0.0
            for record in records:
                effective_conflict = max(record.confidence.conflict_penalty, structural_conflict)
                weight = record.confidence.value * (1.0 - effective_conflict)
                if record.record_type is LearningRecordType.SUCCESS_PATTERN:
                    score += weight
                elif record.record_type is LearningRecordType.FAILURE_PATTERN:
                    score -= weight
                else:
                    if "economic_status=pass" in record.content:
                        score += 0.35 * weight
                    elif "economic_status=fail" in record.content:
                        score -= 0.35 * weight
            score /= max(len(records), 1)
            priors.append(FamilyLearningPrior(
                family, round(score, 6), len(records), successes, failures,
                round(confidence, 6), round(conflict, 6),
            ))
        return tuple(sorted(priors, key=lambda x: (-x.score, x.family)))

    def _opposite_family_records(
        self, *, family: str, market: str, record_type: LearningRecordType, exclude_id: str
    ) -> tuple[LearningRecord, ...]:
        opposite = (
            LearningRecordType.FAILURE_PATTERN
            if record_type is LearningRecordType.SUCCESS_PATTERN
            else LearningRecordType.SUCCESS_PATTERN
            if record_type is LearningRecordType.FAILURE_PATTERN
            else None
        )
        if opposite is None:
            return ()
        return tuple(
            record for record in self.repository.filter(
                scope=LEARNING_SCOPE, project=LEARNING_PROJECT, strategy=family,
                market=market, record_type=opposite,
            ) if record.record_id != exclude_id
        )


def _candidate_record_type(
    candidate: StrategyCandidateRecord, viability: EconomicViabilityStatus
) -> tuple[LearningRecordType, str]:
    if candidate.status is StrategyCandidateStatus.PROMOTION_READY:
        return LearningRecordType.SUCCESS_PATTERN, "promotion_ready_candidate_pattern"
    if candidate.status in {StrategyCandidateStatus.REJECTED, StrategyCandidateStatus.STAGNANT} or viability is EconomicViabilityStatus.FAIL:
        return LearningRecordType.FAILURE_PATTERN, "negative_candidate_pattern"
    return LearningRecordType.RESEARCH_OUTCOME, "candidate_research_outcome"


def _candidate_confidence(candidate: StrategyCandidateRecord, *, conflict_penalty: float) -> ConfidenceScore:
    performance = candidate_cumulative_performance(candidate)
    symbol_component = min(performance.performance_sample_symbols / 20.0, 1.0) * 0.18
    trade_component = min(performance.performance_sample_trades / 100.0, 1.0) * 0.22
    statuses = tuple(str(v).casefold() for v in candidate.validation_stage_status.values())
    passed = sum(status in PASS_LIKE_STAGE_STATUSES for status in statuses)
    stage_component = (passed / max(len(statuses), 7)) * 0.22 if statuses else 0.0
    robustness_component = min(len(candidate.robustness_evidence_symbols) / 5.0, 1.0) * 0.10
    terminal_component = 0.08 if candidate.status in {
        StrategyCandidateStatus.PROMOTION_READY,
        StrategyCandidateStatus.REJECTED,
        StrategyCandidateStatus.STAGNANT,
    } else 0.0
    value = min(0.92, 0.20 + symbol_component + trade_component + stage_component + robustness_component + terminal_component)
    value = max(0.05, value * (1.0 - 0.5 * conflict_penalty))
    return ConfidenceScore(
        round(value, 6),
        "deterministic candidate evidence confidence; confidence ranks research memory but never approves promotion",
        evidence_count=(performance.performance_sample_symbols + performance.performance_sample_trades + len(statuses)),
        validation_state="need_validation",
        recency=1.0,
        conflict_penalty=round(conflict_penalty, 6),
    )


def _candidate_evidence(candidate: StrategyCandidateRecord) -> tuple[EvidenceRecord, ...]:
    items: list[EvidenceRecord] = []
    for symbol, detail in sorted(candidate.breadth_evidence.items()):
        if not bool(detail.get("eligible")):
            continue
        trades = int(detail.get("trade_count", 0) or 0)
        total_return = detail.get("total_return")
        mdd = detail.get("mdd")
        reference = str(detail.get("evidence_id") or f"candidate:{candidate.candidate_id}:breadth:{symbol}")
        items.append(EvidenceRecord(
            f"evidence:{_stable_id(candidate.candidate_id, symbol, reference)}",
            EvidenceType.BACKTEST,
            reference,
            f"symbol={symbol}; trades={trades}; total_return={total_return}; mdd={mdd}; source={detail.get('source','unknown')}",
        ))
        if len(items) >= MAX_EVIDENCE_PER_RECORD:
            break
    for stage, status in sorted(candidate.validation_stage_status.items()):
        if len(items) >= MAX_EVIDENCE_PER_RECORD:
            break
        ref = f"candidate:{candidate.candidate_id}:validation:{stage}:{status}"
        items.append(EvidenceRecord(
            f"evidence:{_stable_id(ref)}", EvidenceType.EXPERIMENT, ref,
            f"validation stage {stage} reported status={status}",
        ))
    if candidate.last_validation_reference and len(items) < MAX_EVIDENCE_PER_RECORD:
        ref = candidate.last_validation_reference
        items.append(EvidenceRecord(
            f"evidence:{_stable_id(candidate.candidate_id, ref)}", EvidenceType.EXPERIMENT, ref,
            "latest candidate validation reference",
        ))
    return tuple(items)


def _candidate_lesson_content(candidate, performance, viability_status, viability_reason: str, outcome: str) -> str:
    passed = sorted(
        stage for stage, status in candidate.validation_stage_status.items()
        if str(status).casefold() in PASS_LIKE_STAGE_STATUSES
    )
    failed = sorted(
        f"{stage}:{status}" for stage, status in candidate.validation_stage_status.items()
        if str(status).casefold() not in PASS_LIKE_STAGE_STATUSES
    )
    return (
        f"strategy_family={candidate.strategy_family}; outcome={outcome}; candidate_status={candidate.status.value}; "
        f"economic_status={viability_status.value}; economic_reason={viability_reason}; "
        f"performance_symbols={performance.performance_sample_symbols}; performance_trades={performance.performance_sample_trades}; "
        f"median_return={performance.median_return}; median_mdd={performance.median_mdd}; "
        f"profitable_symbol_ratio={performance.profitable_symbol_ratio}; "
        f"validation_passed={','.join(passed) if passed else 'none'}; validation_other={','.join(failed) if failed else 'none'}; "
        f"rejected_reason={candidate.rejected_reason or 'none'}"
    )


def _audit_for(record: LearningRecord, previous: LearningRecord | None, now: str) -> AuditEvent:
    return AuditEvent(
        event_id=f"audit:{_stable_id(record.record_id, str(record.version), now)}",
        actor="gaon-learning-v3",
        action=AuditAction.CREATE if previous is None else AuditAction.UPDATE,
        target_ref=record.record_id,
        before_version=previous.version if previous else None,
        after_version=record.version,
        scope=record.scope,
        project=record.project,
        strategy=record.strategy,
        market=record.market,
        evidence=record.evidence,
        timestamp=now,
    )


def _learning_material_key(record: LearningRecord) -> str:
    payload = {
        "type": record.record_type.value,
        "content": record.content,
        "evidence": [(e.evidence_type.value, e.reference, e.summary) for e in record.evidence],
        "confidence": record.confidence.to_dict(),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def learning_summary(connection: sqlite3.Connection, *, market: str | None = None, limit: int = 20) -> dict[str, object]:
    repository = SQLiteLearningRepository(connection)
    records = repository.list_all()
    if market:
        records = tuple(r for r in records if r.market == market)
    records = tuple(sorted(records, key=lambda r: (r.updated_at, r.record_id), reverse=True))[: max(1, min(limit, 50))]
    engine = ProductionLearningEngine(connection)
    details = engine.family_prior_details(market=market) if market else ()
    return {
        "provider": "sqlite:learning_records:v3",
        "count": len(records),
        "records": [r.to_dict() for r in records],
        "family_priors": [item.to_json() for item in details],
        "automatic_promotion": False,
        "strategy_mutated": False,
        "order_executed": False,
    }
